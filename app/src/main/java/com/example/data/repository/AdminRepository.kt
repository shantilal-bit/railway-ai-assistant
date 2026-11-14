package com.example.data.repository

import android.content.ContentResolver
import android.net.Uri
import com.example.data.remote.AdminDocumentDto
import com.example.data.remote.DocumentStatusUpdateDto
import com.example.data.remote.ImportDrivePdfRequestDto
import com.example.data.remote.PresignUploadRequestDto
import com.example.data.remote.RailwayRulesApiService
import com.example.data.remote.RegisterDocumentRequestDto
import com.example.data.remote.ReprocessDocumentRequestDto
import com.example.domain.model.AdminDocumentItem
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.security.MessageDigest

class AdminRepository(
    private val apiService: RailwayRulesApiService,
    private val okHttpClient: OkHttpClient,
) {
    companion object {
        const val MAX_PDF_BYTES: Long = 50L * 1024L * 1024L
        private val PDF_MAGIC = "%PDF-".toByteArray(Charsets.US_ASCII)

        fun validatePdfBytes(bytes: ByteArray) {
            require(bytes.isNotEmpty()) { "Selected PDF file is empty." }
            require(bytes.size <= MAX_PDF_BYTES) { "PDF exceeds the maximum 50 MB upload limit." }
            val headerSlice = bytes.copyOfRange(0, minOf(bytes.size, 1024))
            val hasSignature = indexOfBytes(headerSlice, PDF_MAGIC) >= 0
            require(hasSignature) { "Selected file is not a valid PDF document." }
        }

        private fun indexOfBytes(haystack: ByteArray, needle: ByteArray): Int {
            if (needle.isEmpty() || haystack.size < needle.size) return -1
            outer@ for (i in 0..(haystack.size - needle.size)) {
                for (j in needle.indices) {
                    if (haystack[i + j] != needle[j]) continue@outer
                }
                return i
            }
            return -1
        }
    }

    suspend fun listDocuments(search: String? = null): Result<List<AdminDocumentItem>> {
        return try {
            val cleaned = search?.trim()?.takeIf { it.isNotEmpty() }
            val items = apiService.listAdminDocuments(search = cleaned).map { it.toDomain() }
            Result.success(items)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun uploadPdfAndRegister(
        contentResolver: ContentResolver,
        pdfUri: Uri,
        fileName: String,
        title: String,
        documentNumber: String?,
        documentType: String,
        issuingAuthority: String,
        authorityRank: Int?,
        scopeLevel: String,
        zoneId: String?,
        zoneCode: String,
        divisionId: String?,
        divisionCode: String?,
        departmentId: String?,
        departmentCode: String?,
        issueDate: String?,
        effectiveDate: String?,
        requiresOcr: Boolean,
        supersedesDocumentId: String?,
    ): Result<AdminDocumentItem> = withContext(Dispatchers.IO) {
        try {
            val pdfBytes = contentResolver.openInputStream(pdfUri)?.use { it.readBytes() }
                ?: return@withContext Result.failure(IllegalStateException("Unable to read selected PDF"))

            validatePdfBytes(pdfBytes)

            val sha256 = MessageDigest.getInstance("SHA-256")
                .digest(pdfBytes)
                .joinToString("") { "%02x".format(it) }

            val presign = apiService.presignPdfUpload(
                PresignUploadRequestDto(
                    fileName = fileName,
                    zoneCode = zoneCode,
                    divisionCode = divisionCode,
                    departmentCode = departmentCode,
                ),
            )

            val putRequest = Request.Builder()
                .url(presign.presignedPutUrl)
                .put(pdfBytes.toRequestBody("application/pdf".toMediaType()))
                .build()
            okHttpClient.newCall(putRequest).execute().use { resp ->
                if (!resp.isSuccessful) {
                    return@withContext Result.failure(
                        IllegalStateException("Document upload failed (HTTP ${resp.code})"),
                    )
                }
            }

            val registered = apiService.registerDocument(
                RegisterDocumentRequestDto(
                    title = title.trim(),
                    documentNumber = documentNumber?.trim()?.takeIf { it.isNotEmpty() },
                    documentType = documentType,
                    issuingAuthority = issuingAuthority.trim(),
                    authorityRank = authorityRank,
                    objectKey = presign.objectKey,
                    fileSha256 = sha256,
                    scopeLevel = scopeLevel,
                    zoneId = zoneId,
                    divisionId = divisionId,
                    departmentId = departmentId,
                    issueDate = issueDate?.trim()?.takeIf { it.isNotEmpty() },
                    effectiveDate = effectiveDate?.trim()?.takeIf { it.isNotEmpty() },
                    requiresOcr = requiresOcr,
                    supersedesDocumentId = supersedesDocumentId?.trim()?.takeIf { it.isNotEmpty() },
                ),
            )
            Result.success(registered.toDomain())
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun importGoogleDrivePdf(
        driveUrl: String,
        title: String,
        documentNumber: String?,
        documentType: String,
        issuingAuthority: String,
        authorityRank: Int?,
        scopeLevel: String,
        zoneId: String?,
        zoneCode: String,
        divisionId: String?,
        divisionCode: String?,
        departmentId: String?,
        departmentCode: String?,
        issueDate: String?,
        effectiveDate: String?,
        requiresOcr: Boolean,
        supersedesDocumentId: String?,
    ): Result<AdminDocumentItem> {
        return try {
            val cleanedUrl = driveUrl.trim()
            require(cleanedUrl.startsWith("https://")) {
                "Google Drive link must start with https://"
            }
            val imported = apiService.importDrivePdf(
                ImportDrivePdfRequestDto(
                    driveUrl = cleanedUrl,
                    title = title.trim(),
                    documentNumber = documentNumber?.trim()?.takeIf { it.isNotEmpty() },
                    documentType = documentType,
                    issuingAuthority = issuingAuthority.trim(),
                    authorityRank = authorityRank,
                    scopeLevel = scopeLevel,
                    zoneId = zoneId,
                    zoneCode = zoneCode,
                    divisionId = divisionId,
                    divisionCode = divisionCode,
                    departmentId = departmentId,
                    departmentCode = departmentCode,
                    issueDate = issueDate?.trim()?.takeIf { it.isNotEmpty() },
                    effectiveDate = effectiveDate?.trim()?.takeIf { it.isNotEmpty() },
                    requiresOcr = requiresOcr,
                    supersedesDocumentId = supersedesDocumentId?.trim()?.takeIf { it.isNotEmpty() },
                ),
            )
            Result.success(imported.toDomain())
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun reprocessDocument(
        documentId: String,
        forceOcr: Boolean = false,
    ): Result<AdminDocumentItem> {
        return try {
            val updated = apiService.reprocessDocument(
                documentId = documentId,
                body = ReprocessDocumentRequestDto(forceOcr = forceOcr),
            )
            Result.success(updated.toDomain())
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun updateDocumentStatus(
        documentId: String,
        newStatus: String,
        disabledReason: String? = null,
    ): Result<AdminDocumentItem> {
        return try {
            val updated = apiService.updateDocumentStatus(
                documentId = documentId,
                body = DocumentStatusUpdateDto(status = newStatus, disabledReason = disabledReason),
            )
            Result.success(updated.toDomain())
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    private fun AdminDocumentDto.toDomain(): AdminDocumentItem = AdminDocumentItem(
        id = id,
        title = title,
        documentNumber = documentNumber,
        documentType = documentType,
        issuingAuthority = issuingAuthority,
        authorityRank = authorityRank,
        status = status,
        issueDate = issueDate,
        effectiveDate = effectiveDate,
        requiresOcr = requiresOcr,
        ocrStatus = ocrStatus,
        ingestionStatus = ingestionStatus,
        ingestionError = ingestionError,
        chunkCount = chunkCount,
        indexedAt = indexedAt,
        sourceType = sourceType,
        sourceUrl = sourceUrl,
        pageCount = pageCount,
    )
}
