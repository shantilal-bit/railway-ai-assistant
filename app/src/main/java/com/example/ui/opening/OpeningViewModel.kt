package com.example.ui.opening

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.example.core.config.AppPreferences
import com.example.data.repository.AuthRepository
import com.example.data.repository.TaxonomyRepository
import com.example.domain.model.BackendHealth
import com.example.domain.model.RailwayDepartment
import com.example.domain.model.RailwayDivision
import com.example.domain.model.RailwayZone
import com.example.domain.model.UserProfile
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

data class OpeningUiState(
    val zones: List<RailwayZone> = emptyList(),
    val divisions: List<RailwayDivision> = emptyList(),
    val departments: List<RailwayDepartment> = emptyList(),
    val selectedZone: RailwayZone? = null,
    val selectedDivision: RailwayDivision? = null,
    val selectedDepartment: RailwayDepartment? = null,
    val backendBaseUrl: String = "",
    val backendHealth: BackendHealth? = null,
    val userProfile: UserProfile? = null,
    val isSyncing: Boolean = false,
    val syncMessage: String? = null,
    val syncError: String? = null,
) {
    val canProceedToChat: Boolean
        get() = selectedZone != null && selectedDivision != null && selectedDepartment != null
}

@OptIn(ExperimentalCoroutinesApi::class)
class OpeningViewModel(
    private val taxonomyRepository: TaxonomyRepository,
    private val authRepository: AuthRepository,
    private val preferences: AppPreferences,
) : ViewModel() {

    private val selectedZoneId = MutableStateFlow<String?>(null)
    private val selectedDivisionId = MutableStateFlow<String?>(null)
    private val selectedDepartmentId = MutableStateFlow<String?>(null)
    private val backendHealth = MutableStateFlow<BackendHealth?>(null)
    private val isSyncing = MutableStateFlow(false)
    private val syncMessage = MutableStateFlow<String?>(null)
    private val syncError = MutableStateFlow<String?>(null)

    private val divisionsFlow = selectedZoneId.flatMapLatest { zoneId ->
        if (zoneId != null) taxonomyRepository.divisionsForZone(zoneId) else flowOf(emptyList())
    }

    val uiState: StateFlow<OpeningUiState> = combine(
        taxonomyRepository.activeZones,
        divisionsFlow,
        taxonomyRepository.activeDepartments,
        combine(selectedZoneId, selectedDivisionId, selectedDepartmentId) { z, d, dept ->
            Triple(z, d, dept)
        },
        combine(
            preferences.backendBaseUrlFlow,
            backendHealth,
            authRepository.currentUser,
            isSyncing,
            combine(syncMessage, syncError) { msg, err -> msg to err },
        ) { url, health, user, syncing, status ->
            Quintuple(url, health, user, syncing, status)
        },
    ) { zones, divisions, departments, selection, meta ->
        val activeZone = zones.firstOrNull { it.id == selection.first }
        val activeDivision = divisions.firstOrNull { it.id == selection.second }
        val activeDepartment = departments.firstOrNull { it.id == selection.third }

        OpeningUiState(
            zones = zones,
            divisions = divisions,
            departments = departments,
            selectedZone = activeZone,
            selectedDivision = activeDivision,
            selectedDepartment = activeDepartment,
            backendBaseUrl = meta.first,
            backendHealth = meta.second,
            userProfile = meta.third,
            isSyncing = meta.fourth,
            syncMessage = meta.fifth.first,
            syncError = meta.fifth.second,
        )
    }.stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(5_000),
        initialValue = OpeningUiState(),
    )

    init {
        viewModelScope.launch {
            // Restore cached selection for offline use before live sync runs
            val saved = preferences.selectionFlow.first()
            selectedZoneId.value = saved.zoneId
            selectedDivisionId.value = saved.divisionId
            selectedDepartmentId.value = saved.departmentId

            // Automatically sync taxonomy from Backend /v1/taxonomy on app open
            syncTaxonomyInternal()
        }
    }

    fun selectZone(zone: RailwayZone) {
        if (selectedZoneId.value != zone.id) {
            selectedZoneId.value = zone.id
            selectedDivisionId.value = null
            syncMessage.value = null
        }
    }

    fun selectDivision(division: RailwayDivision) {
        selectedDivisionId.value = division.id
        syncMessage.value = null
    }

    fun selectDepartment(department: RailwayDepartment) {
        selectedDepartmentId.value = department.id
        syncMessage.value = null
    }

    fun persistSelection() {
        val state = uiState.value
        val zone = state.selectedZone ?: return
        val division = state.selectedDivision ?: return
        val department = state.selectedDepartment ?: return
        viewModelScope.launch {
            preferences.saveSelection(zone.id, division.id, department.id)
        }
    }

    fun syncTaxonomy() {
        viewModelScope.launch {
            syncTaxonomyInternal()
        }
    }

    private suspend fun syncTaxonomyInternal() {
        isSyncing.value = true
        syncMessage.value = null
        syncError.value = null

        val result = taxonomyRepository.syncFromBackend(includeInactiveZones = false)
        result.fold(
            onSuccess = { summary ->
                // Reset old selected IDs after sync so no stale/invalid selection remains
                selectedZoneId.value = null
                selectedDivisionId.value = null
                selectedDepartmentId.value = null
                preferences.clearSelection()
                syncMessage.value = summary
            },
            onFailure = { error ->
                syncError.value = buildString {
                    append("Taxonomy sync failed: ")
                    append(error.localizedMessage ?: error.javaClass.simpleName)
                    append(". Showing offline Room cache if available.")
                }
            },
        )
        backendHealth.value = taxonomyRepository.checkBackendHealth()
        isSyncing.value = false
    }

    fun updateBackendBaseUrl(newUrl: String) {
        val cleaned = newUrl.trim()
        if (cleaned.isEmpty()) return
        viewModelScope.launch {
            preferences.saveBackendBaseUrl(cleaned)
            syncTaxonomyInternal()
        }
    }

    fun dismissSyncMessage() {
        syncMessage.value = null
        syncError.value = null
    }

    private data class Quintuple<A, B, C, D, E>(
        val first: A,
        val second: B,
        val third: C,
        val fourth: D,
        val fifth: E,
    )

    class Factory(
        private val taxonomyRepository: TaxonomyRepository,
        private val authRepository: AuthRepository,
        private val preferences: AppPreferences,
    ) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            OpeningViewModel(taxonomyRepository, authRepository, preferences) as T
    }
}
