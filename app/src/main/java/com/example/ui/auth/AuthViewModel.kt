package com.example.ui.auth

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import com.example.data.repository.AuthRepository
import com.example.domain.model.UserProfile
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

data class AuthUiState(
    val userProfile: UserProfile? = null,
    val isLoading: Boolean = false,
    val statusMessage: String? = null,
    val isError: Boolean = false,
)

class AuthViewModel(
    private val authRepository: AuthRepository,
) : ViewModel() {

    private val isLoading = MutableStateFlow(false)
    private val statusMessage = MutableStateFlow<String?>(null)
    private val isError = MutableStateFlow(false)

    val uiState: StateFlow<AuthUiState> = combine(
        authRepository.currentUser,
        isLoading,
        statusMessage,
        isError,
    ) { profile, loading, msg, error ->
        AuthUiState(
            userProfile = profile,
            isLoading = loading,
            statusMessage = msg,
            isError = error,
        )
    }.stateIn(
        scope = viewModelScope,
        started = SharingStarted.WhileSubscribed(5_000),
        initialValue = AuthUiState(),
    )

    fun login(email: String, password: String) {
        if (email.isBlank() || password.isBlank()) {
            isError.value = true
            statusMessage.value = "Please enter your railway email and password."
            return
        }
        viewModelScope.launch {
            isLoading.value = true
            statusMessage.value = null
            isError.value = false
            val res = authRepository.login(email, password)
            res.fold(
                onSuccess = {
                    statusMessage.value = "Signed in as ${it.fullName ?: it.email} (${it.role.apiValue})"
                },
                onFailure = {
                    isError.value = true
                    statusMessage.value = it.localizedMessage ?: "Sign in failed. Please check your credentials and connection."
                },
            )
            isLoading.value = false
        }
    }

    fun signup(email: String, password: String, fullName: String, employeeId: String?) {
        if (email.isBlank() || password.length < 6 || fullName.isBlank()) {
            isError.value = true
            statusMessage.value = "Enter full name, valid email, and password (min 6 characters)."
            return
        }
        viewModelScope.launch {
            isLoading.value = true
            statusMessage.value = null
            isError.value = false
            val res = authRepository.signup(email, password, fullName, employeeId)
            res.fold(
                onSuccess = { statusMessage.value = it },
                onFailure = {
                    isError.value = true
                    statusMessage.value = it.localizedMessage ?: "Registration failed."
                },
            )
            isLoading.value = false
        }
    }

    fun logout() {
        viewModelScope.launch {
            authRepository.logout()
            isError.value = false
            statusMessage.value = "Signed out."
        }
    }

    class Factory(private val authRepository: AuthRepository) : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T = AuthViewModel(authRepository) as T
    }
}
