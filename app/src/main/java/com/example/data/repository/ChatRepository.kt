package com.example.data.repository

import android.content.ContentResolver
import android.net.Uri
import com.example.data.local.ChatMessageEntity
import com.example.data.local.ChatSessionEntity
import com.example.data.local.RailwayDao
import com.example.data.remote.ChatAskRequestDto
import com.example.data.remote.ChatAskResponseDto
import com.example.data.remote.ChatHistoryTurnDto
import com.example.data.remote.GeminiRulesDataSource
import com.example.data.remote.RailwayRulesApiService
import com.example.data.remote.SourceCitationDto
import com.example.domain.model.AiEngineMode
import com.example.domain.model.ChatMessage
import com.example.domain.model.ChatSession
import com.example.domain.model.MessageSender
import com.example.domain.model.QueryLanguage
import com.example.domain.model.RailwayDepartment
import com.example.domain.model.RailwayDivision
import com.example.domain.model.RailwayZone
import com.example.domain.model.SourceCitation
import com.example.domain.model.StructuredRuleAnswer
import com.squareup.moshi.Moshi
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import retrofit2.HttpException
import java.io.IOException
import java.util.UUID

class ChatRepository(
    private val dao: RailwayDao,
    private val apiService: RailwayRulesApiService,
    private val geminiDataSource: GeminiRulesDataSource,
    moshi: Moshi,
) {
    private val answerAdapter = moshi.adapter(ChatAskResponseDto::class.java)

    val sessions: Flow<List<ChatSession>> = dao.observeChatSessions().map { list ->
        list.map {
            ChatSession(
                id = it.id,
                title = it.title,
                zoneId = it.zoneId,
                zoneName = it.zoneName,
                divisionId = it.divisionId,
                divisionName = it.divisionName,
                departmentId = it.departmentId,
                departmentName = it.departmentName,
                updatedAtMillis = it.updatedAtMillis,
            )
        }
    }

    fun observeMessages(sessionId: String): Flow<List<ChatMessage>> =
        dao.observeMessagesForSession(sessionId).map { list ->
            list.map { entity ->
                val sender = runCatching { MessageSender.valueOf(entity.sender) }
                    .getOrDefault(MessageSender.ASSISTANT)
                val structured = entity.structuredAnswerJson?.let { raw ->
                    runCatching { answerAdapter.fromJson(raw)?.toDomain() }.getOrNull()
                }
                ChatMessage(
                    id = entity.id,
                    sessionId = entity.sessionId,
                    sender = sender,
                    text = entity.text,
                    language = entity.language,
                    structuredAnswer = structured,
                    createdAtMillis = entity.createdAtMillis,
                )
            }
        }

    suspend fun createOrLoadSession(
        existingSessionId: String?,
        zone: RailwayZone,
        division: RailwayDivision,
        department: RailwayDepartment,
    ): ChatSession {
        if (!existingSessionId.isNullOrBlank()) {
            val found = dao.getSessionById(existingSessionId)
            if (found != null) {
                return ChatSession(
                    id = found.id,
                    title = found.title,
                    zoneId = found.zoneId,
                    zoneName = found.zoneName,
                    divisionId = found.divisionId,
                    divisionName = found.divisionName,
                    departmentId = found.departmentId,
                    departmentName = found.departmentName,
                    updatedAtMillis = found.updatedAtMillis,
                )
            }
        }

        val now = System.currentTimeMillis()
        val entity = ChatSessionEntity(
            id = UUID.randomUUID().toString(),
            title = "${zone.code} • ${division.name} • ${department.name}",
            zoneId = zone.id,
            zoneName = zone.name,
            divisionId = division.id,
            divisionName = division.name,
            departmentId = department.id,
            departmentName = department.name,
            updatedAtMillis = now,
        )
        dao.upsertSession(entity)
        return ChatSession(
            id = entity.id,
            title = entity.title,
            zoneId = entity.zoneId,
            zoneName = entity.zoneName,
            divisionId = entity.divisionId,
            divisionName = entity.divisionName,
            departmentId = entity.departmentId,
            departmentName = entity.departmentName,
            updatedAtMillis = entity.updatedAtMillis,
        )
    }

    suspend fun deleteSession(sessionId: String) {
        dao.deleteSession(sessionId)
    }

    suspend fun askQuestion(
        session: ChatSession,
        questionText: String,
        preferredLanguage: QueryLanguage,
        engineMode: AiEngineMode,
        attachedPdfUri: Uri? = null,
        attachedPdfName: String? = null,
        contentResolver: ContentResolver? = null,
    ) {
        val trimmed = questionText.trim()
        if (trimmed.isEmpty()) return

        val now = System.currentTimeMillis()
        val detectedLang = if (trimmed.any { it in '\u0900'..'\u097F' }) "hi" else "en"

        val updatedTitle = if (dao.getMessagesForSession(session.id).isEmpty()) {
            trimmed.take(56)
        } else {
            session.title
        }
        dao.upsertSession(
            ChatSessionEntity(
                id = session.id,
                title = updatedTitle,
                zoneId = session.zoneId,
                zoneName = session.zoneName,
                divisionId = session.divisionId,
                divisionName = session.divisionName,
                departmentId = session.departmentId,
                departmentName = session.departmentName,
                updatedAtMillis = now,
            ),
        )

        val userDisplay = if (engineMode == AiEngineMode.GEMINI_FIREBASE && !attachedPdfName.isNullOrBlank()) {
            "$trimmed\n[Attached PDF: $attachedPdfName]"
        } else {
            trimmed
        }

        val userMsg = ChatMessageEntity(
            id = UUID.randomUUID().toString(),
            sessionId = session.id,
            sender = MessageSender.USER.name,
            text = userDisplay,
            language = detectedLang,
            structuredAnswerJson = null,
            createdAtMillis = now,
        )
        dao.insertMessage(userMsg)

        val priorMessages = dao.getMessagesForSession(session.id)
            .filter { it.id != userMsg.id && it.sender != MessageSender.SYSTEM_ERROR.name }
            .takeLast(6)

        try {
            val responseDto: ChatAskResponseDto = when (engineMode) {
                AiEngineMode.GEMINI_FIREBASE -> {
                    val answer = geminiDataSource.askWithGemini(
                        zoneName = session.zoneName,
                        divisionName = session.divisionName,
                        departmentName = session.departmentName,
                        question = trimmed,
                        preferredLanguage = preferredLanguage,
                        recentHistory = priorMessages.map { msg ->
                            (if (msg.sender == MessageSender.USER.name) "user" else "model") to msg.text
                        },
                        attachedPdfUri = attachedPdfUri,
                        attachedPdfName = attachedPdfName,
                        contentResolver = contentResolver,
                    )
                    answer.toDto()
                }

                AiEngineMode.BACKEND_RAG -> {
                    apiService.askRule(
                        ChatAskRequestDto(
                            sessionId = session.id,
                            zoneId = session.zoneId,
                            divisionId = session.divisionId,
                            departmentId = session.departmentId,
                            question = trimmed,
                            preferredLanguage = preferredLanguage.code,
                            history = priorMessages.map {
                                ChatHistoryTurnDto(
                                    role = if (it.sender == MessageSender.USER.name) "user" else "assistant",
                                    content = it.text,
                                )
                            },
                        ),
                    )
                }
            }

            val json = answerAdapter.toJson(responseDto)
            dao.insertMessage(
                ChatMessageEntity(
                    id = UUID.randomUUID().toString(),
                    sessionId = session.id,
                    sender = MessageSender.ASSISTANT.name,
                    text = responseDto.directAnswer,
                    language = responseDto.responseLanguage,
                    structuredAnswerJson = json,
                    createdAtMillis = System.currentTimeMillis(),
                ),
            )
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            val honestError = when (e) {
                is HttpException -> when (e.code()) {
                    401 -> "Authentication required (HTTP 401). Please sign in under Employee Account to query the Backend RAG Server."
                    429 -> "Rate limit reached (HTTP 429). Please wait a moment before sending another question."
                    else -> "Backend returned HTTP ${e.code()}: ${e.message()}. No answer was generated."
                }
                is IOException -> if (engineMode == AiEngineMode.BACKEND_RAG) {
                    "Unable to reach the Railway Rules Backend API (${e.javaClass.simpleName}). " +
                        "Check your Backend Server URL in Connection Settings, or switch to Gemini AI (Firebase) above."
                } else {
                    "Network error while contacting Gemini via Firebase AI Logic: ${e.localizedMessage ?: e.javaClass.simpleName}."
                }
                else -> e.localizedMessage ?: "AI request failed (${e.javaClass.simpleName})."
            }
            dao.insertMessage(
                ChatMessageEntity(
                    id = UUID.randomUUID().toString(),
                    sessionId = session.id,
                    sender = MessageSender.SYSTEM_ERROR.name,
                    text = honestError,
                    language = "en",
                    structuredAnswerJson = null,
                    createdAtMillis = System.currentTimeMillis(),
                ),
            )
        }
    }

    private fun StructuredRuleAnswer.toDto(): ChatAskResponseDto = ChatAskResponseDto(
        responseLanguage = responseLanguage,
        isReliableAnswerFound = isReliableAnswerFound,
        directAnswer = directAnswer,
        detailedExplanation = detailedExplanation,
        applicableRuleNumber = applicableRuleNumber,
        officialDocumentName = officialDocumentName,
        pdfPageNumber = pdfPageNumber,
        amendmentOrCircularRef = amendmentOrCircularRef,
        effectiveDate = effectiveDate,
        conflictWarning = conflictWarning,
        aiProvider = aiProvider,
        modelName = modelName,
        citations = citations.map {
            SourceCitationDto(
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

    private fun ChatAskResponseDto.toDomain(): StructuredRuleAnswer = StructuredRuleAnswer(
        responseLanguage = responseLanguage,
        isReliableAnswerFound = isReliableAnswerFound,
        directAnswer = directAnswer,
        detailedExplanation = detailedExplanation,
        applicableRuleNumber = applicableRuleNumber,
        officialDocumentName = officialDocumentName,
        pdfPageNumber = pdfPageNumber,
        amendmentOrCircularRef = amendmentOrCircularRef,
        effectiveDate = effectiveDate,
        conflictWarning = conflictWarning,
        aiProvider = aiProvider,
        modelName = modelName,
        citations = citations.map {
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
}
