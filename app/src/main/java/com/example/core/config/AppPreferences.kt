package com.example.core.config

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import com.example.BuildConfig
import com.example.domain.model.QueryLanguage
import com.example.domain.model.UserProfile
import com.example.domain.model.UserRole
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore(name = "railway_rules_prefs")

data class UserSelection(
    val zoneId: String?,
    val divisionId: String?,
    val departmentId: String?,
    val queryLanguage: QueryLanguage,
)

class AppPreferences(private val context: Context) {

    private object Keys {
        val SELECTED_ZONE_ID = stringPreferencesKey("selected_zone_id")
        val SELECTED_DIVISION_ID = stringPreferencesKey("selected_division_id")
        val SELECTED_DEPARTMENT_ID = stringPreferencesKey("selected_department_id")
        val QUERY_LANGUAGE = stringPreferencesKey("query_language")
        val BACKEND_BASE_URL = stringPreferencesKey("backend_base_url")
        val ACCESS_TOKEN = stringPreferencesKey("access_token")
        val REFRESH_TOKEN = stringPreferencesKey("refresh_token")
        val USER_ID = stringPreferencesKey("user_id")
        val USER_EMAIL = stringPreferencesKey("user_email")
        val USER_FULL_NAME = stringPreferencesKey("user_full_name")
        val USER_EMPLOYEE_ID = stringPreferencesKey("user_employee_id")
        val USER_ROLE = stringPreferencesKey("user_role")
    }

    val selectionFlow: Flow<UserSelection> = context.dataStore.data.map { prefs ->
        UserSelection(
            zoneId = prefs[Keys.SELECTED_ZONE_ID],
            divisionId = prefs[Keys.SELECTED_DIVISION_ID],
            departmentId = prefs[Keys.SELECTED_DEPARTMENT_ID],
            queryLanguage = QueryLanguage.entries.firstOrNull {
                it.code == prefs[Keys.QUERY_LANGUAGE]
            } ?: QueryLanguage.AUTO,
        )
    }

    val backendBaseUrlFlow: Flow<String> = context.dataStore.data.map { prefs ->
        prefs[Keys.BACKEND_BASE_URL]?.takeIf { it.isNotBlank() }
            ?: BuildConfig.DEFAULT_BACKEND_BASE_URL
    }

    val userProfileFlow: Flow<UserProfile?> = context.dataStore.data.map { prefs ->
        val id = prefs[Keys.USER_ID] ?: return@map null
        val email = prefs[Keys.USER_EMAIL] ?: return@map null
        UserProfile(
            id = id,
            email = email,
            fullName = prefs[Keys.USER_FULL_NAME],
            employeeId = prefs[Keys.USER_EMPLOYEE_ID],
            role = UserRole.fromApi(prefs[Keys.USER_ROLE]),
        )
    }

    suspend fun getAccessToken(): String? = context.dataStore.data.first()[Keys.ACCESS_TOKEN]

    suspend fun getBackendBaseUrl(): String = backendBaseUrlFlow.first()

    suspend fun saveSelection(zoneId: String, divisionId: String, departmentId: String) {
        context.dataStore.edit { prefs ->
            prefs[Keys.SELECTED_ZONE_ID] = zoneId
            prefs[Keys.SELECTED_DIVISION_ID] = divisionId
            prefs[Keys.SELECTED_DEPARTMENT_ID] = departmentId
        }
    }

    suspend fun saveQueryLanguage(language: QueryLanguage) {
        context.dataStore.edit { prefs ->
            prefs[Keys.QUERY_LANGUAGE] = language.code
        }
    }

    suspend fun saveBackendBaseUrl(url: String) {
        val normalized = if (url.endsWith("/")) url else "$url/"
        context.dataStore.edit { prefs ->
            prefs[Keys.BACKEND_BASE_URL] = normalized
        }
    }

    suspend fun saveAuthSession(
        accessToken: String,
        refreshToken: String?,
        profile: UserProfile,
    ) {
        context.dataStore.edit { prefs ->
            prefs[Keys.ACCESS_TOKEN] = accessToken
            if (refreshToken != null) prefs[Keys.REFRESH_TOKEN] = refreshToken
            prefs[Keys.USER_ID] = profile.id
            prefs[Keys.USER_EMAIL] = profile.email
            if (profile.fullName != null) prefs[Keys.USER_FULL_NAME] = profile.fullName
            if (profile.employeeId != null) prefs[Keys.USER_EMPLOYEE_ID] = profile.employeeId
            prefs[Keys.USER_ROLE] = profile.role.apiValue
        }
    }

    suspend fun clearAuthSession() {
        context.dataStore.edit { prefs ->
            prefs.remove(Keys.ACCESS_TOKEN)
            prefs.remove(Keys.REFRESH_TOKEN)
            prefs.remove(Keys.USER_ID)
            prefs.remove(Keys.USER_EMAIL)
            prefs.remove(Keys.USER_FULL_NAME)
            prefs.remove(Keys.USER_EMPLOYEE_ID)
            prefs.remove(Keys.USER_ROLE)
        }
    }
}
