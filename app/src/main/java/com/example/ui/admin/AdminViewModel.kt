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
import com.example.domain.model.ScopeLevel
import com.example.domain.model.UserProfile
import com.example.domain.model.UserRole
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

data class AdminUiState(
    val userProfile: UserProfile? = null,
    val zones: List<RailwayZone> = emptyList(),
    val divisions: List<RailwayDivision> = emptyList(),
    val departments: List<RailwayDepartment> = emptyList(),
    val selectedZoneId: String? = null,
    val documents: List<AdminDocumentItem> = emptyList(),
    val searchQuery: String = "",
    val isLoading: Boolean = false,
    val statusMessage: String? = null,
    val isError: Boolean = false,
) {
    val isAdmin: Boolean get() = userProfile?.role == UserRole.ADMIN
}

@OptIn(ExperimentalCoroutinesApi::class)
class AdminViewModel(
    private val adminRepository: AdminRepository,
    private val authRepository: AuthRepository,
    private val taxonomyRepository: TaxonomyRepository,
) : ViewModel() {

    private val selectedZoneId = MutableStateFlow<String?>(null)
    private val documents = MutableStateFlow<List<AdminDocumentItem>>(emptyList())
    private val searchQuery = MutableStateFlow("")
    private val isLoading = MutableStateFlow(false)
    private val statusMessage = MutableStateFlow<String?>(null)
    private val isError = MutableStateFlow(false)
    private var pollingJob: Job? = null

    private val divisionsForSelectedZone = combine(
        taxonomyRepository.allZones,
        selectedZoneId,
    ) { zones, chosenId ->
        chosenId ?: zones.firstOrNull()?.id
    }.flatMapLatest { zoneId ->
        if (zoneId != null) taxonomyRepository.divisionsForZone(zoneId) else flowOf(emptyList())
    }

    val uiState: StateFlow<AdminUiState> = combine(
        authRepository.currentUser,
        taxonomyRepository.allZones,
        divisionsForSelectedZone,
        taxonomyRepository.activeDepartments,
        combine(selectedZoneId, documents, searchQuery, combine(isLoading, statusMessage, isError) { l, m, e -> Triple(l, m, e) }) { zId, docs, query, meta ->
            AdminMeta(zId, docs, query, meta.first, meta.second, meta.third)
        },
    ) { user, zones, divisions, departments, meta ->
        AdminUiState(
            userProfile = user,
            zones = zones,
            divisions = divisions,
            departments = departments,
            selectedZoneId = meta.selectedZoneId ?: zones.firstOrNull()?.id,
            documents = meta.documents,
            searchQuery = meta.searchQuery,
            isLoading = meta.isLoading,
            statusMessage = meta.statusMessage,
            isError = meta.isError,
        )
    }.stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(5_000),
        initialValue = AdminUiState(),
    )

    fun selectZone(zoneId: String) {
        selectedZoneId.value = zoneId
    }

    fun onSearchQueryChanged(query: String) {
        searchQuery.value = query
        refreshDocuments(search = query, showLoading = false)
    }

    fun refreshDocuments(search: String = searchQuery.value, showLoading: Boolean = true) {
        viewModelScope.launch {
            if (showLoading) {
                isLoading.value = true
                isError.value = false
            }
            adminRepository.listDocuments(search).fold(
                onSuccess = { items ->
                    documents.value = items
                    schedulePollingIfNeeded(items)
                },
                onFailure = {
                    isError.value = true
                    statusMessage.value = it.localizedMessage ?: "Unable to fetch admin document registry."
                },
            )
            if (showLoading) {
                isLoading.value = false
            }
        }
    }

    private fun schedulePollingIfNeeded(items: List<AdminDocumentItem>) {
        val hasPending = items.any {
            it.ingestionStatus == "pending" || it.ingestionStatus == "processing"
        }
        if (!hasPending) {
            pollingJob?.cancel()
            pollingJob = null
            return
        }
        if (pollingJob?.isActive == true) return
        pollingJob = viewModelScope.launch {
            repeat(12) {
                delay(4_000)
                val res = adminRepository.listDocuments(searchQuery.value)
                val refreshed = res.getOrNull() ?: return@repeat
                documents.value = refreshed
                if (refreshed.none { it.ingestionStatus == "pending" || it.ingestionStatus == "processing" }) {
                    return@launch
                }
            }
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
        authorityRank: Int?,
        scopeLevel: ScopeLevel,
        zone: RailwayZone?,
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
            statusMessage.value = "Uploading official PDF and starting indexing…"
            adminRepository.uploadPdfAndRegister(
                contentResolver = contentResolver,
                pdfUri = pdfUri,
                fileName = fileName,
                title = title,
                documentNumber = documentNumber,
                documentType = documentType,
                issuingAuthority = issuingAuthority,
                authorityRank = authorityRank,
                scopeLevel = scopeLevel.apiValue,
                zoneId = zone?.id,
                zoneCode = zone?.code ?: "COMMON",
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
                    statusMessage.value = "Uploaded '${item.title}' (Ingestion: ${item.ingestionStatus})."
                    upsertLocalDocument(item)
                    schedulePollingIfNeeded(documents.value)
                },
                onFailure = {
                    isError.value = true
                    statusMessage.value = it.localizedMessage ?: "Admin upload failed."
                },
            )
            isLoading.value = false
        }
    }

    fun importGoogleDrivePdf(
        driveUrl: String,
        title: String,
        documentNumber: String?,
        documentType: String,
        issuingAuthority: String,
        authorityRank: Int?,
        scopeLevel: ScopeLevel,
        zone: RailwayZone?,
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
            statusMessage.value = "Importing Google Drive PDF and starting indexing…"
            adminRepository.importGoogleDrivePdf(
                driveUrl = driveUrl,
                title = title,
                documentNumber = documentNumber,
                documentType = documentType,
                issuingAuthority = issuingAuthority,
                authorityRank = authorityRank,
                scopeLevel = scopeLevel.apiValue,
                zoneId = zone?.id,
                zoneCode = zone?.code ?: "COMMON",
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
                    statusMessage.value = "Imported '${item.title}' (Ingestion: ${item.ingestionStatus})."
                    upsertLocalDocument(item)
                    schedulePollingIfNeeded(documents.value)
                },
                onFailure = {
                    isError.value = true
                    statusMessage.value = it.localizedMessage ?: "Google Drive import failed."
                },
            )
            isLoading.value = false
        }
    }

    fun reprocessDocument(documentId: String, forceOcr: Boolean = false) {
        viewModelScope.launch {
            isLoading.value = true
            isError.value = false
            statusMessage.value = "Re-processing PDF chunks & embeddings…"
            adminRepository.reprocessDocument(documentId, forceOcr).fold(
                onSuccess = { updated ->
                    upsertLocalDocument(updated)
                    statusMessage.value = "Re-indexing started for '${updated.title}'."
                    schedulePollingIfNeeded(documents.value)
                },
                onFailure = {
                    isError.value = true
                    statusMessage.value = it.localizedMessage ?: "Re-process request failed."
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
                    upsertLocalDocument(updated)
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

    private fun upsertLocalDocument(item: AdminDocumentItem) {
        val current = documents.value
        documents.value = if (current.any { it.id == item.id }) {
            current.map { if (it.id == item.id) item else it }
        } else {
            listOf(item) + current
        }
    }

    private data class AdminMeta(
        val selectedZoneId: String?,
        val documents: List<AdminDocumentItem>,
        val searchQuery: String,
        val isLoading: Boolean,
        val statusMessage: String?,
        val isError: Boolean,
    )

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
