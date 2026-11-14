package com.example.ui.chat

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.example.core.config.AppPreferences
import com.example.data.repository.ChatRepository
import com.example.data.repository.TaxonomyRepository
import com.example.domain.model.BackendHealth
import com.example.domain.model.ChatMessage
import com.example.domain.model.ChatSession
import com.example.domain.model.QueryLanguage
import com.example.domain.model.RailwayDepartment
import com.example.domain.model.RailwayDivision
import com.example.domain.model.RailwayZone
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

data class ChatUiState(
    val activeSession: ChatSession? = null,
    val messages: List<ChatMessage> = emptyList(),
    val sessions: List<ChatSession> = emptyList(),
    val draftInput: String = "",
    val queryLanguage: QueryLanguage = QueryLanguage.AUTO,
    val isGenerating: Boolean = false,
    val backendHealth: BackendHealth? = null,
    val backendBaseUrl: String = "",
    val activeZone: RailwayZone? = null,
    val activeDivision: RailwayDivision? = null,
    val activeDepartment: RailwayDepartment? = null,
)

@OptIn(ExperimentalCoroutinesApi::class)
class ChatViewModel(
    private val chatRepository: ChatRepository,
    private val taxonomyRepository: TaxonomyRepository,
    private val preferences: AppPreferences,
) : ViewModel() {

    private val activeSession = MutableStateFlow<ChatSession?>(null)
    private val draftInput = MutableStateFlow("")
    private val isGenerating = MutableStateFlow(false)
    private val backendHealth = MutableStateFlow<BackendHealth?>(null)
    private val activeScope = MutableStateFlow<Triple<RailwayZone?, RailwayDivision?, RailwayDepartment?>>(
        Triple(null, null, null),
    )

    private val messagesFlow = activeSession.flatMapLatest { session ->
        if (session != null) chatRepository.observeMessages(session.id) else flowOf(emptyList())
    }

    val uiState: StateFlow<ChatUiState> = combine(
        activeSession,
        messagesFlow,
        chatRepository.sessions,
        combine(draftInput, isGenerating, preferences.selectionFlow) { draft, gen, sel ->
            InputState(draft, gen, sel.queryLanguage)
        },
        combine(backendHealth, preferences.backendBaseUrlFlow, activeScope) { health, url, scope ->
            Triple(health, url, scope)
        },
    ) { session, messages, sessions, input, envMeta ->
        ChatUiState(
            activeSession = session,
            messages = messages,
            sessions = sessions,
            draftInput = input.draft,
            isGenerating = input.isGenerating,
            queryLanguage = input.language,
            backendHealth = envMeta.first,
            backendBaseUrl = envMeta.second,
            activeZone = envMeta.third.first,
            activeDivision = envMeta.third.second,
            activeDepartment = envMeta.third.third,
        )
    }.stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(5_000),
        initialValue = ChatUiState(),
    )

    fun initializeScope(
        zone: RailwayZone,
        division: RailwayDivision,
        department: RailwayDepartment,
        existingSessionId: String? = null,
    ) {
        activeScope.value = Triple(zone, division, department)
        viewModelScope.launch {
            val current = activeSession.value
            val needsNew = current == null ||
                (existingSessionId != null && current.id != existingSessionId) ||
                current.zoneId != zone.id ||
                current.divisionId != division.id ||
                current.departmentId != department.id

            if (needsNew) {
                activeSession.value = chatRepository.createOrLoadSession(
                    existingSessionId = existingSessionId,
                    zone = zone,
                    division = division,
                    department = department,
                )
            }
            backendHealth.value = taxonomyRepository.checkBackendHealth()
        }
    }

    fun onDraftChanged(text: String) {
        draftInput.value = text
    }

    fun setPromptSuggestion(question: String) {
        draftInput.value = question
    }

    fun setQueryLanguage(language: QueryLanguage) {
        viewModelScope.launch {
            preferences.saveQueryLanguage(language)
        }
    }

    fun startNewChat() {
        val (zone, division, department) = activeScope.value
        if (zone == null || division == null || department == null) return
        viewModelScope.launch {
            activeSession.value = chatRepository.createOrLoadSession(
                existingSessionId = null,
                zone = zone,
                division = division,
                department = department,
            )
        }
    }

    fun selectSession(session: ChatSession) {
        activeSession.value = session
    }

    fun deleteSession(sessionId: String) {
        viewModelScope.launch {
            val deletingActive = activeSession.value?.id == sessionId
            chatRepository.deleteSession(sessionId)
            if (deletingActive) {
                startNewChat()
            }
        }
    }

    fun sendQuestion() {
        val session = activeSession.value ?: return
        val question = draftInput.value.trim()
        if (question.isEmpty() || isGenerating.value) return

        draftInput.value = ""
        viewModelScope.launch {
            isGenerating.value = true
            chatRepository.askQuestion(
                session = session,
                questionText = question,
                preferredLanguage = uiState.value.queryLanguage,
            )
            isGenerating.value = false
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

    private data class InputState(
        val draft: String,
        val isGenerating: Boolean,
        val language: QueryLanguage,
    )

    class Factory(
        private val chatRepository: ChatRepository,
        private val taxonomyRepository: TaxonomyRepository,
        private val preferences: AppPreferences,
    ) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T =
            ChatViewModel(chatRepository, taxonomyRepository, preferences) as T
    }
}
