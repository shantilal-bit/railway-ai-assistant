package com.example.data.repository

import android.content.ContentResolver
import android.net.Uri
import com.example.data.remote.AdminDocumentDto
import com.example.data.remote.DocumentStatusUpdateDto
import com.example.data.remote.PresignUploadRequestDto
import com.example.data.remote.RailwayRulesApiService
import com.example.data.remote.RegisterDocumentRequestDto
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
    suspend fun listDocuments(): Result<List<AdminDocumentItem>> {
        return try {
            val items = apiService.listAdminDocuments().map { it.toDomain() }
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
        zoneId: String,
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
                    objectKey = presign.objectKey,
                    fileSha256 = sha256,
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
        status = status,
        issueDate = issueDate,
        effectiveDate = effectiveDate,
        requiresOcr = requiresOcr,
        ocrStatus = ocrStatus,
        pageCount = pageCount,
    )
}
