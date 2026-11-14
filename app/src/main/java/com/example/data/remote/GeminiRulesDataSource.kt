package com.example.data.remote

import android.content.ContentResolver
import android.net.Uri
import android.util.Log
import com.example.domain.model.QueryLanguage
import com.example.domain.model.SourceCitation
import com.example.domain.model.StructuredRuleAnswer
import com.google.firebase.Firebase
import com.google.firebase.ai.ai
import com.google.firebase.ai.type.Schema
import com.google.firebase.ai.type.content
import com.google.firebase.ai.type.generationConfig
import com.squareup.moshi.Moshi
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeout

private const val TAG = "GeminiRulesDataSource"
private const val MAX_INLINE_PDF_BYTES = 18 * 1024 * 1024 // Stay safely below 20MB inline limit

class GeminiRulesDataSource(moshi: Moshi) {

    private val responseAdapter = moshi.adapter(ChatAskResponseDto::class.java)

    private val structuredSchema = Schema.obj(
        properties = mapOf(
            "responseLanguage" to Schema.enumeration(
                values = listOf("en", "hi"),
                description = "Language code matching the user's question ('hi' for Hindi, 'en' for English).",
            ),
            "isReliableAnswerFound" to Schema.boolean(
                description = "True only when the answer is directly grounded in an attached official PDF or verified statutory rule; false when unverified.",
            ),
            "directAnswer" to Schema.string(
                description = "Concise direct answer in the user's language.",
            ),
            "detailedExplanation" to Schema.string(
                description = "Clear explanation in simple language, noting any amendments, applicability, or conflicting instructions.",
            ),
            "applicableRuleNumber" to Schema.string(
                description = "Exact rule/para/clause number if verified, otherwise state clearly that official document verification is required.",
            ),
            "officialDocumentName" to Schema.string(
                description = "Exact official Railway manual, code, or circular name if verified, otherwise state 'No official PDF attached / verify in Railway Board manual'.",
            ),
            "pdfPageNumber" to Schema.string(
                description = "Exact PDF page number when an official PDF is attached, otherwise 'Not verified (attach PDF or connect backend)'.",
            ),
            "amendmentOrCircularRef" to Schema.string(
                description = "Amendment slip or circular reference if applicable.",
                nullable = true,
            ),
            "effectiveDate" to Schema.string(
                description = "Effective date if available in the source.",
                nullable = true,
            ),
            "conflictWarning" to Schema.string(
                description = "Notice if instructions conflict or if an older rule is superseded.",
                nullable = true,
            ),
            "citations" to Schema.array(
                items = Schema.obj(
                    properties = mapOf(
                        "documentId" to Schema.string(),
                        "documentTitle" to Schema.string(),
                        "documentNumber" to Schema.string(nullable = true),
                        "ruleNumber" to Schema.string(nullable = true),
                        "pageNumber" to Schema.integer(),
                        "searchTier" to Schema.integer(),
                        "searchTierLabel" to Schema.string(),
                        "effectiveDate" to Schema.string(nullable = true),
                        "isSuperseded" to Schema.boolean(),
                        "excerpt" to Schema.string(),
                    ),
                    optionalProperties = listOf("documentNumber", "ruleNumber", "effectiveDate"),
                ),
                description = "Exact page-level citations from any attached official PDF.",
            ),
        ),
        optionalProperties = listOf("amendmentOrCircularRef", "effectiveDate", "conflictWarning"),
    )

    private val model by lazy {
        Firebase.ai.generativeModel(
            modelName = "gemini-3.8-flash",
            generationConfig = generationConfig {
                temperature = 0.1f
                responseMimeType = "application/json"
                responseSchema = structuredSchema
            },
            systemInstruction = content {
                text(
                    """
                    You are an Indian Railway Rules AI Assistant.
                    STRICT ACCURACY & ANTI-HALLUCINATION RULES:
                    1. Understand questions in Hindi or English and reply in the EXACT SAME language as the user's question (unless a specific language override is requested).
                    2. If an official Railway PDF is attached to the prompt, analyze the English or Hindi PDF thoroughly and cite the exact rule number, official document title, PDF page number, issue/effective date, and amendments from that PDF.
                    3. NEVER invent or guess a Railway rule number, RBE circular number, effective date, or PDF page number.
                    4. If no official PDF is attached and you cannot verify an exact citation with certainty, set "isReliableAnswerFound" to false, explain clearly in the user's language what is uncertain or requires checking the official Western Railway / Railway Board PDF, and do not fabricate circular numbers or page numbers.
                    5. Respect legal authority: Railway Board circulars and latest effective amendments override conflicting older divisional or departmental instructions.
                    """.trimIndent(),
                )
            },
        )
    }

    suspend fun askWithGemini(
        zoneName: String,
        divisionName: String,
        departmentName: String,
        question: String,
        preferredLanguage: QueryLanguage,
        recentHistory: List<Pair<String, String>>,
        attachedPdfUri: Uri? = null,
        attachedPdfName: String? = null,
        contentResolver: ContentResolver? = null,
    ): StructuredRuleAnswer {
        val pdfBytes: ByteArray? = if (attachedPdfUri != null && contentResolver != null) {
            withContext(Dispatchers.IO) {
                contentResolver.openInputStream(attachedPdfUri)?.use { input ->
                    val bytes = input.readBytes()
                    if (bytes.size > MAX_INLINE_PDF_BYTES) {
                        throw IllegalArgumentException(
                            "Selected PDF exceeds the 18 MB inline limit for direct Gemini analysis. Use the Backend RAG Server for larger manuals.",
                        )
                    }
                    bytes
                }
            }
        } else {
            null
        }

        val historyText = if (recentHistory.isEmpty()) {
            "None"
        } else {
            recentHistory.takeLast(6).joinToString("\n") { (role, text) -> "$role: $text" }
        }

        val promptText = buildString {
            appendLine("Selected Railway Scope: Zone = $zoneName | Division = $divisionName | Department = $departmentName")
            appendLine("Language Preference: ${preferredLanguage.label} (${preferredLanguage.code})")
            if (!attachedPdfName.isNullOrBlank()) {
                appendLine("Attached Official PDF Filename: $attachedPdfName")
            } else {
                appendLine("Attached Official PDF: None (no local PDF attached; do NOT fabricate circular numbers or PDF page numbers).")
            }
            appendLine("Recent Conversation Context:")
            appendLine(historyText)
            appendLine()
            appendLine("Employee Question:")
            appendLine(question)
        }

        return try {
            val response = withTimeout(60_000L) {
                if (pdfBytes != null) {
                    model.generateContent(
                        content {
                            inlineData(pdfBytes, "application/pdf")
                            text(promptText)
                        },
                    )
                } else {
                    model.generateContent(promptText)
                }
            }
            val rawJson = response.text
                ?: throw IllegalStateException("Gemini returned an empty response.")

            val dto = responseAdapter.fromJson(rawJson)
                ?: throw IllegalStateException("Unable to parse structured Gemini response.")

            StructuredRuleAnswer(
                responseLanguage = dto.responseLanguage,
                isReliableAnswerFound = dto.isReliableAnswerFound,
                directAnswer = dto.directAnswer,
                detailedExplanation = dto.detailedExplanation,
                applicableRuleNumber = dto.applicableRuleNumber,
                officialDocumentName = dto.officialDocumentName,
                pdfPageNumber = dto.pdfPageNumber,
                amendmentOrCircularRef = dto.amendmentOrCircularRef,
                effectiveDate = dto.effectiveDate,
                conflictWarning = dto.conflictWarning,
                aiProvider = "Firebase AI Logic (Gemini)",
                modelName = "gemini-3.8-flash",
                citations = dto.citations.map {
                    SourceCitation(
                        documentId = it.documentId,
                        documentTitle = it.documentTitle,
                        documentNumber = it.documentNumber,
                        ruleNumber = it.ruleNumber,
                        pageNumber = it.pageNumber,
                        searchTier = it.searchTier,
                        searchTierLabel = it.searchTierLabel,
                        effectiveDate = it.effectiveDate,
                        isSuperseded = it.isSuperseded,
                        excerpt = it.excerpt,
                    )
                },
            )
        } catch (e: TimeoutCancellationException) {
            Log.e(TAG, "Gemini generation timed out", e)
            throw IllegalStateException("Gemini request timed out after 60 seconds. Please try again.", e)
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            Log.e(TAG, "Firebase AI Logic generation failed", e)
            throw e
        }
    }
}
