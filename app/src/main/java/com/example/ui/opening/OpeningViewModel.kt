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

    private val divisionsFlow = combine(
        taxonomyRepository.activeZones,
        selectedZoneId,
    ) { zones, chosenZoneId ->
        chosenZoneId ?: zones.firstOrNull()?.id
    }.flatMapLatest { zoneId ->
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
            syncMessage,
        ) { url, health, user, syncing, msg ->
            Quintuple(url, health, user, syncing, msg)
        },
    ) { zones, divisions, departments, selection, meta ->
        val activeZone = zones.firstOrNull { it.id == selection.first } ?: zones.firstOrNull()
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
            syncMessage = meta.fifth,
        )
    }.stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(5_000),
        initialValue = OpeningUiState(),
    )

    init {
        viewModelScope.launch {
            taxonomyRepository.ensureSeeded()
            preferences.selectionFlow.collect { saved ->
                if (selectedZoneId.value == null && saved.zoneId != null) {
                    selectedZoneId.value = saved.zoneId
                }
                if (selectedDivisionId.value == null && saved.divisionId != null) {
                    selectedDivisionId.value = saved.divisionId
                }
                if (selectedDepartmentId.value == null && saved.departmentId != null) {
                    selectedDepartmentId.value = saved.departmentId
                }
            }
        }
        checkBackendHealth()
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
            isSyncing.value = true
            syncMessage.value = null
            val result = taxonomyRepository.syncFromBackend()
            syncMessage.value = result.fold(
                onSuccess = { it },
                onFailure = {
                    "Sync unavailable (${it.javaClass.simpleName}). Using local Western Railway catalog."
                },
            )
            backendHealth.value = taxonomyRepository.checkBackendHealth()
            isSyncing.value = false
        }
    }

    fun checkBackendHealth() {
        viewModelScope.launch {
            backendHealth.value = taxonomyRepository.checkBackendHealth()
        }
    }

    fun updateBackendBaseUrl(newUrl: String) {
        val cleaned = newUrl.trim()
        if (cleaned.isEmpty()) return
        viewModelScope.launch {
            preferences.saveBackendBaseUrl(cleaned)
            backendHealth.value = taxonomyRepository.checkBackendHealth()
        }
    }

    fun dismissSyncMessage() {
        syncMessage.value = null
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
