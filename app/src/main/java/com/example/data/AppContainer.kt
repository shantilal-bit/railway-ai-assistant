package com.example.data

import android.app.Application
import com.example.core.config.AppPreferences
import com.example.data.local.RailwayDatabase
import com.example.data.remote.GeminiRulesDataSource
import com.example.data.remote.NetworkModule
import com.example.data.repository.AdminRepository
import com.example.data.repository.AuthRepository
import com.example.data.repository.ChatRepository
import com.example.data.repository.TaxonomyRepository
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob

class AppContainer(application: Application) {
    private val appScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    val preferences = AppPreferences(application)
    val database = RailwayDatabase.create(application, appScope)
    val moshi = NetworkModule.createMoshi()
    val okHttpClient = NetworkModule.createOkHttpClient(preferences)
    val apiService = NetworkModule.createApiService(okHttpClient = okHttpClient, moshi = moshi)
    val geminiDataSource = GeminiRulesDataSource(moshi = moshi)

    val taxonomyRepository = TaxonomyRepository(
        dao = database.railwayDao(),
        apiService = apiService,
        preferences = preferences,
    )

    val chatRepository = ChatRepository(
        dao = database.railwayDao(),
        apiService = apiService,
        geminiDataSource = geminiDataSource,
        moshi = moshi,
    )

    val authRepository = AuthRepository(
        apiService = apiService,
        preferences = preferences,
    )

    val adminRepository = AdminRepository(
        apiService = apiService,
        okHttpClient = okHttpClient,
    )
}
