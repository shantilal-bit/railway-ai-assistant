package com.example.data.repository

import com.example.core.config.AppPreferences
import com.example.data.remote.LoginRequestDto
import com.example.data.remote.RailwayRulesApiService
import com.example.data.remote.SignupRequestDto
import com.example.domain.model.UserProfile
import com.example.domain.model.UserRole
import kotlinx.coroutines.flow.Flow

class AuthRepository(
    private val apiService: RailwayRulesApiService,
    private val preferences: AppPreferences,
) {
    val currentUser: Flow<UserProfile?> = preferences.userProfileFlow

    suspend fun login(email: String, password: String): Result<UserProfile> {
        return try {
            val response = apiService.login(LoginRequestDto(email.trim(), password))
            val profile = UserProfile(
                id = response.user.id,
                email = response.user.email,
                fullName = response.user.fullName,
                employeeId = response.user.employeeId,
                role = UserRole.fromApi(response.user.role),
            )
            preferences.saveAuthSession(response.accessToken, response.refreshToken, profile)
            Result.success(profile)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun signup(
        email: String,
        password: String,
        fullName: String,
        employeeId: String?,
    ): Result<String> {
        return try {
            apiService.signup(
                SignupRequestDto(
                    email = email.trim(),
                    password = password,
                    fullName = fullName.trim(),
                    employeeId = employeeId?.trim()?.takeIf { it.isNotEmpty() },
                ),
            )
            Result.success("Account created. Please sign in with your credentials.")
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun logout() {
        preferences.clearAuthSession()
    }
}
