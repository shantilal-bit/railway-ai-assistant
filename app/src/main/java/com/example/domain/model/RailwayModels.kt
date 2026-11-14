package com.example.domain.model

enum class AiEngineMode(val label: String) {
    GEMINI_FIREBASE("Gemini AI (Firebase)"),
    BACKEND_RAG("Backend RAG"),
}

enum class QueryLanguage(val code: String, val label: String) {
    AUTO("auto", "Auto (EN / हिन्दी)"),
    ENGLISH("en", "English"),
    HINDI("hi", "हिन्दी"),
}

enum class UserRole(val apiValue: String) {
    EMPLOYEE("employee"),
    REVIEWER("reviewer"),
    ADMIN("admin");

    companion object {
        fun fromApi(value: String?): UserRole =
            entries.firstOrNull { it.apiValue.equals(value, ignoreCase = true) } ?: EMPLOYEE
    }
}

enum class SearchTier(
    val tier: Int,
    val title: String,
    val description: String,
) {
    SELECTED_DEPARTMENT(
        1,
        "Selected Department Documents",
        "Manuals, JPOs, and circulars issued specifically for your chosen department.",
    ),
    DIVISION_OTHER_DEPARTMENTS(
        2,
        "Other Departments in Selected Division",
        "Cross-departmental divisional instructions and joint procedural orders.",
    ),
    ZONE_WIDE(
        3,
        "Western Railway Zone-Wide",
        "Headquarters policy circulars and General & Subsidiary Rules applicable across the Zone.",
    ),
    RAILWAY_BOARD(
        4,
        "Railway Board Rules & Circulars",
        "Ministry of Railways RBE circulars, IREM, IREC, and statutory codes (highest authority).",
    ),
    COMMON_RAILWAY(
        5,
        "Other Common Railway Documents",
        "General service, conduct, vigilance, and common establishment manuals.",
    ),
}

data class RailwayZone(
    val id: String,
    val code: String,
    val name: String,
    val nameHi: String?,
    val isActive: Boolean,
    val sortOrder: Int,
)

data class RailwayDivision(
    val id: String,
    val zoneId: String,
    val code: String,
    val name: String,
    val nameHi: String?,
    val isActive: Boolean,
    val sortOrder: Int,
)

data class RailwayDepartment(
    val id: String,
    val code: String,
    val name: String,
    val nameHi: String?,
    val isActive: Boolean,
    val sortOrder: Int,
)

data class SourceCitation(
    val documentId: String,
    val documentTitle: String,
    val documentNumber: String?,
    val ruleNumber: String?,
    val pageNumber: Int,
    val searchTier: Int,
    val searchTierLabel: String,
    val effectiveDate: String?,
    val isSuperseded: Boolean,
    val excerpt: String,
)

data class StructuredRuleAnswer(
    val responseLanguage: String,
    val isReliableAnswerFound: Boolean,
    val directAnswer: String,
    val detailedExplanation: String,
    val applicableRuleNumber: String,
    val officialDocumentName: String,
    val pdfPageNumber: String,
    val amendmentOrCircularRef: String?,
    val effectiveDate: String?,
    val conflictWarning: String?,
    val aiProvider: String?,
    val modelName: String?,
    val citations: List<SourceCitation>,
)

enum class MessageSender {
    USER,
    ASSISTANT,
    SYSTEM_ERROR,
}

data class ChatMessage(
    val id: String,
    val sessionId: String,
    val sender: MessageSender,
    val text: String,
    val language: String,
    val structuredAnswer: StructuredRuleAnswer? = null,
    val createdAtMillis: Long,
)

data class ChatSession(
    val id: String,
    val title: String,
    val zoneId: String,
    val zoneName: String,
    val divisionId: String,
    val divisionName: String,
    val departmentId: String,
    val departmentName: String,
    val updatedAtMillis: Long,
)

data class UserProfile(
    val id: String,
    val email: String,
    val fullName: String?,
    val employeeId: String?,
    val role: UserRole,
)

data class BackendHealth(
    val isConnected: Boolean,
    val baseUrl: String,
    val aiProvider: String? = null,
    val database: String? = null,
    val storage: String? = null,
    val message: String,
)

data class AdminDocumentItem(
    val id: String,
    val title: String,
    val documentNumber: String?,
    val documentType: String,
    val issuingAuthority: String,
    val status: String,
    val issueDate: String?,
    val effectiveDate: String?,
    val requiresOcr: Boolean,
    val ocrStatus: String,
    val pageCount: Int?,
)
