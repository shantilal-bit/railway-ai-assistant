package com.example.data.repository

import com.example.core.config.AppPreferences
import com.example.data.remote.LoginRequestDto
import com.example.data.remote.RailwayRulesApiService
import com.example.data.remote.RefreshTokenRequestDto
import com.example.data.remote.SignupRequestDto
import com.example.domain.model.UserProfile
import com.example.domain.model.UserRole
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import retrofit2.HttpException

class AuthRepository(
    private val apiService: RailwayRulesApiService,
    private val preferences: AppPreferences,
) {
    private val refreshMutex = Mutex()
    private val sessionWriteMutex = Mutex()
    private var inFlightRefresh: CompletableDeferred<Result<UserProfile>>? = null

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
            sessionWriteMutex.withLock {
                preferences.saveAuthSession(response.accessToken, response.refreshToken, profile)
            }
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

    suspend fun refreshSession(): Result<UserProfile> {
        val existingDeferred: CompletableDeferred<Result<UserProfile>>?
        val ownDeferred: CompletableDeferred<Result<UserProfile>>?

        refreshMutex.withLock {
            val current = inFlightRefresh
            if (current != null && current.isActive) {
                existingDeferred = current
                ownDeferred = null
            } else {
                val created = CompletableDeferred<Result<UserProfile>>()
                inFlightRefresh = created
                existingDeferred = null
                ownDeferred = created
            }
        }

        if (existingDeferred != null) {
            return existingDeferred.await()
        }

        val created = ownDeferred!!
        val result = try {
            executeSingleRefresh()
        } catch (ce: CancellationException) {
            created.complete(Result.failure(ce))
            refreshMutex.withLock {
                if (inFlightRefresh === created) {
                    inFlightRefresh = null
                }
            }
            throw ce
        } catch (t: Throwable) {
            Result.failure(t)
        }

        created.complete(result)
        refreshMutex.withLock {
            if (inFlightRefresh === created) {
                inFlightRefresh = null
            }
        }
        return result
    }

    private suspend fun executeSingleRefresh(): Result<UserProfile> {
        val refreshToken = preferences.getRefreshToken()?.takeIf { it.isNotBlank() }
            ?: return Result.failure(IllegalStateException("No refresh token available"))
        return try {
            val response = apiService.refreshSession(RefreshTokenRequestDto(refreshToken))
            val profile = UserProfile(
                id = response.user.id,
                email = response.user.email,
                fullName = response.user.fullName,
                employeeId = response.user.employeeId,
                role = UserRole.fromApi(response.user.role),
            )
            sessionWriteMutex.withLock {
                // Only update if user hasn't signed in with a newer session or logged out mid-flight
                if (preferences.getRefreshToken() == refreshToken) {
                    preferences.saveAuthSession(
                        accessToken = response.accessToken,
                        refreshToken = response.refreshToken ?: refreshToken,
                        profile = profile,
                    )
                }
            }
            Result.success(profile)
        } catch (e: HttpException) {
            if (e.code() == 401) {
                sessionWriteMutex.withLock {
                    if (preferences.getRefreshToken() == refreshToken) {
                        preferences.clearAuthSession()
                    }
                }
            }
            Result.failure(e)
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun logout() {
        sessionWriteMutex.withLock {
            preferences.clearAuthSession()
        }
    }
}
