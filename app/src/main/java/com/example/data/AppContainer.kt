package com.example.data

import android.app.Application
import com.example.core.config.AppPreferences
import com.example.data.local.RailwayDatabase
import com.example.data.remote.NetworkModule
import com.example.data.repository.AdminRepository
import com.example.data.repository.AuthRepository
import com.example.data.repository.ChatRepository
import com.example.data.repository.TaxonomyRepository

class AppContainer(application: Application) {
    val preferences = AppPreferences(application)
    val database = RailwayDatabase.create(application)
    val moshi = NetworkModule.createMoshi()
    val okHttpClient = NetworkModule.createOkHttpClient(preferences)
    val r2UploadOkHttpClient = NetworkModule.createR2UploadOkHttpClient()
    val apiService = NetworkModule.createApiService(okHttpClient = okHttpClient, moshi = moshi)

    val taxonomyRepository = TaxonomyRepository(
        dao = database.railwayDao(),
        apiService = apiService,
        preferences = preferences,
    )

    val authRepository = AuthRepository(
        apiService = apiService,
        preferences = preferences,
    )

    val chatRepository = ChatRepository(
        dao = database.railwayDao(),
        apiService = apiService,
        moshi = moshi,
        onRefreshAuthSession = { authRepository.refreshSession().isSuccess },
    )

    val adminRepository = AdminRepository(
        apiService = apiService,
        r2OkHttpClient = r2UploadOkHttpClient,
    )
}
