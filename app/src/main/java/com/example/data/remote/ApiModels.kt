package com.example.data.remote

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class HealthResponseDto(
    val status: String,
    val aiProvider: String? = null,
    val storage: String? = null,
    val database: String? = null,
)

@JsonClass(generateAdapter = true)
data class ZoneDto(
    val id: String,
    val code: String,
    val name: String,
    @Json(name = "name_hi") val nameHi: String? = null,
    @Json(name = "is_active") val isActive: Boolean = true,
    @Json(name = "sort_order") val sortOrder: Int = 100,
)

@JsonClass(generateAdapter = true)
data class DivisionDto(
    val id: String,
    @Json(name = "zone_id") val zoneId: String,
    val code: String,
    val name: String,
    @Json(name = "name_hi") val nameHi: String? = null,
    @Json(name = "is_active") val isActive: Boolean = true,
    @Json(name = "sort_order") val sortOrder: Int = 100,
)

@JsonClass(generateAdapter = true)
data class DepartmentDto(
    val id: String,
    val code: String,
    val name: String,
    @Json(name = "name_hi") val nameHi: String? = null,
    @Json(name = "is_active") val isActive: Boolean = true,
    @Json(name = "sort_order") val sortOrder: Int = 100,
)

@JsonClass(generateAdapter = true)
data class TaxonomyResponseDto(
    val zones: List<ZoneDto>,
    val divisions: List<DivisionDto>,
    val departments: List<DepartmentDto>,
)

@JsonClass(generateAdapter = true)
data class LoginRequestDto(
    val email: String,
    val password: String,
)

@JsonClass(generateAdapter = true)
data class SignupRequestDto(
    val email: String,
    val password: String,
    val fullName: String,
    val employeeId: String? = null,
)

@JsonClass(generateAdapter = true)
data class UserProfileDto(
    val id: String,
    val email: String,
    @Json(name = "full_name") val fullName: String? = null,
    @Json(name = "employee_id") val employeeId: String? = null,
    val role: String? = "employee",
)

@JsonClass(generateAdapter = true)
data class AuthSessionResponseDto(
    val accessToken: String,
    val refreshToken: String? = null,
    val user: UserProfileDto,
)

@JsonClass(generateAdapter = true)
data class SignupResponseDto(
    val status: String,
    val userId: String? = null,
)

@JsonClass(generateAdapter = true)
data class ChatHistoryTurnDto(
    val role: String,
    val content: String,
)

@JsonClass(generateAdapter = true)
data class ChatAskRequestDto(
    val sessionId: String,
    val zoneId: String,
    val divisionId: String,
    val departmentId: String,
    val question: String,
    val preferredLanguage: String = "auto",
    val history: List<ChatHistoryTurnDto> = emptyList(),
)

@JsonClass(generateAdapter = true)
data class SourceCitationDto(
    val documentId: String,
    val documentTitle: String,
    val documentNumber: String? = null,
    val ruleNumber: String? = null,
    val pageNumber: Int = 1,
    val searchTier: Int = 1,
    val searchTierLabel: String = "",
    val effectiveDate: String? = null,
    val isSuperseded: Boolean = false,
    val excerpt: String = "",
)

@JsonClass(generateAdapter = true)
data class ChatAskResponseDto(
    val responseLanguage: String = "en",
    val isReliableAnswerFound: Boolean = false,
    val directAnswer: String,
    val detailedExplanation: String,
    val applicableRuleNumber: String = "Not specified",
    val officialDocumentName: String = "Not specified",
    val pdfPageNumber: String = "Not specified",
    val amendmentOrCircularRef: String? = null,
    val effectiveDate: String? = null,
    val conflictWarning: String? = null,
    val aiProvider: String? = null,
    val modelName: String? = null,
    val citations: List<SourceCitationDto> = emptyList(),
)

@JsonClass(generateAdapter = true)
data class AdminDocumentDto(
    val id: String,
    val title: String,
    @Json(name = "document_number") val documentNumber: String? = null,
    @Json(name = "document_type") val documentType: String,
    @Json(name = "issuing_authority") val issuingAuthority: String,
    @Json(name = "authority_rank") val authorityRank: Int = 50,
    val status: String,
    @Json(name = "issue_date") val issueDate: String? = null,
    @Json(name = "effective_date") val effectiveDate: String? = null,
    @Json(name = "requires_ocr") val requiresOcr: Boolean = false,
    @Json(name = "ocr_status") val ocrStatus: String = "not_needed",
    @Json(name = "ingestion_status") val ingestionStatus: String = "pending",
    @Json(name = "ingestion_error") val ingestionError: String? = null,
    @Json(name = "chunk_count") val chunkCount: Int = 0,
    @Json(name = "indexed_at") val indexedAt: String? = null,
    @Json(name = "source_type") val sourceType: String = "r2_upload",
    @Json(name = "source_url") val sourceUrl: String? = null,
    @Json(name = "page_count") val pageCount: Int? = null,
)

@JsonClass(generateAdapter = true)
data class PresignUploadRequestDto(
    val fileName: String,
    val zoneCode: String,
    val divisionCode: String? = null,
    val departmentCode: String? = null,
)

@JsonClass(generateAdapter = true)
data class PresignUploadResponseDto(
    val objectKey: String,
    val presignedPutUrl: String,
)

@JsonClass(generateAdapter = true)
data class RegisterDocumentRequestDto(
    val title: String,
    val documentNumber: String? = null,
    val documentType: String,
    val issuingAuthority: String,
    val authorityRank: Int? = null,
    val objectKey: String,
    val fileSha256: String,
    val scopeLevel: String = "DEPARTMENT",
    val zoneId: String? = null,
    val divisionId: String? = null,
    val departmentId: String? = null,
    val issueDate: String? = null,
    val effectiveDate: String? = null,
    val requiresOcr: Boolean = false,
    val supersedesDocumentId: String? = null,
)

@JsonClass(generateAdapter = true)
data class ImportDrivePdfRequestDto(
    val driveUrl: String,
    val title: String,
    val documentNumber: String? = null,
    val documentType: String,
    val issuingAuthority: String,
    val authorityRank: Int? = null,
    val scopeLevel: String = "DEPARTMENT",
    val zoneId: String? = null,
    val zoneCode: String = "WR",
    val divisionId: String? = null,
    val divisionCode: String? = null,
    val departmentId: String? = null,
    val departmentCode: String? = null,
    val issueDate: String? = null,
    val effectiveDate: String? = null,
    val requiresOcr: Boolean = false,
    val supersedesDocumentId: String? = null,
)

@JsonClass(generateAdapter = true)
data class ReprocessDocumentRequestDto(
    val forceOcr: Boolean = false,
)

@JsonClass(generateAdapter = true)
data class DocumentStatusUpdateDto(
    val status: String,
    val disabledReason: String? = null,
)
