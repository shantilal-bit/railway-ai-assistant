package com.example.ui.admin

import android.content.ContentResolver
import android.net.Uri
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.example.data.repository.AdminRepository
import com.example.data.repository.AuthRepository
import com.example.data.repository.TaxonomyRepository
import com.example.domain.model.AdminDocumentItem
import com.example.domain.model.RailwayDepartment
import com.example.domain.model.RailwayDivision
import com.example.domain.model.RailwayZone
import com.example.domain.model.UserProfile
import com.example.domain.model.UserRole
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

data class AdminUiState(
    val userProfile: UserProfile? = null,
    val zones: List<RailwayZone> = emptyList(),
    val divisions: List<RailwayDivision> = emptyList(),
    val departments: List<RailwayDepartment> = emptyList(),
    val documents: List<AdminDocumentItem> = emptyList(),
    val isLoading: Boolean = false,
    val statusMessage: String? = null,
    val isError: Boolean = false,
) {
    val isAdmin: Boolean get() = userProfile?.role == UserRole.ADMIN
}

class AdminViewModel(
    private val adminRepository: AdminRepository,
    private val authRepository: AuthRepository,
    private val taxonomyRepository: TaxonomyRepository,
) : ViewModel() {

    private val documents = MutableStateFlow<List<AdminDocumentItem>>(emptyList())
    private val isLoading = MutableStateFlow(false)
    private val statusMessage = MutableStateFlow<String?>(null)
    private val isError = MutableStateFlow(false)
    private val selectedZoneId = MutableStateFlow("wr-zone-001")

    val uiState: StateFlow<AdminUiState> = combine(
        authRepository.currentUser,
        taxonomyRepository.allZones,
        taxonomyRepository.divisionsForZone(selectedZoneId.value),
        taxonomyRepository.activeDepartments,
        combine(documents, isLoading, statusMessage, isError) { docs, loading, msg, err ->
            Quad(docs, loading, msg, err)
        },
    ) { user, zones, divisions, departments, meta ->
        AdminUiState(
            userProfile = user,
            zones = zones,
            divisions = divisions,
            departments = departments,
            documents = meta.first,
            isLoading = meta.second,
            statusMessage = meta.third,
            isError = meta.fourth,
        )
    }.stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(5_000),
        initialValue = AdminUiState(),
    )

    fun refreshDocuments() {
        viewModelScope.launch {
            isLoading.value = true
            isError.value = false
            statusMessage.value = null
            adminRepository.listDocuments().fold(
                onSuccess = { documents.value = it },
                onFailure = {
                    isError.value = true
                    statusMessage.value = it.localizedMessage ?: "Unable to fetch admin document registry."
                },
            )
            isLoading.value = false
        }
    }

    fun uploadAndRegisterPdf(
        contentResolver: ContentResolver,
        pdfUri: Uri,
        fileName: String,
        title: String,
        documentNumber: String?,
        documentType: String,
        issuingAuthority: String,
        zone: RailwayZone,
        division: RailwayDivision?,
        department: RailwayDepartment?,
        issueDate: String?,
        effectiveDate: String?,
        requiresOcr: Boolean,
        supersedesDocumentId: String?,
    ) {
        viewModelScope.launch {
            isLoading.value = true
            isError.value = false
            statusMessage.value = "Uploading PDF to Cloudflare R2 and registering metadata…"
            adminRepository.uploadPdfAndRegister(
                contentResolver = contentResolver,
                pdfUri = pdfUri,
                fileName = fileName,
                title = title,
                documentNumber = documentNumber,
                documentType = documentType,
                issuingAuthority = issuingAuthority,
                zoneId = zone.id,
                zoneCode = zone.code,
                divisionId = division?.id,
                divisionCode = division?.code,
                departmentId = department?.id,
                departmentCode = department?.code,
                issueDate = issueDate,
                effectiveDate = effectiveDate,
                requiresOcr = requiresOcr,
                supersedesDocumentId = supersedesDocumentId,
            ).fold(
                onSuccess = { item ->
                    statusMessage.value = "Uploaded '${item.title}' (${item.status}). Ready for review/OCR."
                    documents.value = listOf(item) + documents.value
                },
                onFailure = {
                    isError.value = true
                    statusMessage.value = it.localizedMessage ?: "Admin upload failed."
                },
            )
            isLoading.value = false
        }
    }

    fun updateStatus(documentId: String, newStatus: String, reason: String? = null) {
        viewModelScope.launch {
            isLoading.value = true
            isError.value = false
            adminRepository.updateDocumentStatus(documentId, newStatus, reason).fold(
                onSuccess = { updated ->
                    documents.value = documents.value.map { if (it.id == updated.id) updated else it }
                    statusMessage.value = "Updated '${updated.title}' to $newStatus."
                },
                onFailure = {
                    isError.value = true
                    statusMessage.value = it.localizedMessage ?: "Status update failed."
                },
            )
            isLoading.value = false
        }
    }

    private data class Quad<A, B, C, D>(val first: A, val second: B, val third: C, val fourth: D)

    class Factory(
        private val adminRepository: AdminRepository,
        private val authRepository: AuthRepository,
        private val taxonomyRepository: TaxonomyRepository,
    ) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            AdminViewModel(adminRepository, authRepository, taxonomyRepository) as T
    }
}
