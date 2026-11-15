package com.example.data.remote

import com.example.BuildConfig
import com.example.core.config.AppPreferences
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlinx.coroutines.runBlocking
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Response
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import java.util.concurrent.TimeUnit

class DynamicBaseUrlInterceptor(
    private val baseUrlProvider: () -> String,
    private val defaultBaseUrlProvider: () -> String = { BuildConfig.DEFAULT_BACKEND_BASE_URL },
) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val original = chain.request()
        val configured = baseUrlProvider().toHttpUrlOrNull()
        val defaultBackendHost = defaultBaseUrlProvider().toHttpUrlOrNull()?.host

        val shouldRewrite = configured != null &&
            (defaultBackendHost == null || original.url.host.equals(defaultBackendHost, ignoreCase = true))

        if (shouldRewrite && configured != null) {
            val newUrl = original.url.newBuilder()
                .scheme(configured.scheme)
                .host(configured.host)
                .port(configured.port)
                .build()
            return chain.proceed(original.newBuilder().url(newUrl).build())
        }
        return chain.proceed(original)
    }
}

class AuthInterceptor(
    private val tokenProvider: () -> String?,
    private val allowedHostsProvider: () -> Set<String> = { emptySet() },
) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val original = chain.request()
        val allowedHosts = allowedHostsProvider()
        val isBackendRequest = allowedHosts.isEmpty() ||
            allowedHosts.any { it.equals(original.url.host, ignoreCase = true) }

        val token = tokenProvider()
        val request = if (isBackendRequest && !token.isNullOrBlank()) {
            original.newBuilder()
                .addHeader("Authorization", "Bearer $token")
                .build()
        } else {
            original
        }
        return chain.proceed(request)
    }
}

object NetworkModule {

    fun createMoshi(): Moshi = Moshi.Builder()
        .addLast(KotlinJsonAdapterFactory())
        .build()

    internal fun resolveBackendHosts(
        configuredBaseUrl: String?,
        defaultBaseUrl: String = BuildConfig.DEFAULT_BACKEND_BASE_URL,
    ): Set<String> {
        val hosts = linkedSetOf<String>()
        defaultBaseUrl.toHttpUrlOrNull()?.host?.let(hosts::add)
        configuredBaseUrl?.toHttpUrlOrNull()?.host?.let(hosts::add)
        return hosts
    }

    fun createOkHttpClient(preferences: AppPreferences): OkHttpClient {
        val logging = HttpLoggingInterceptor().apply {
            level = if (BuildConfig.DEBUG) {
                HttpLoggingInterceptor.Level.BASIC
            } else {
                HttpLoggingInterceptor.Level.NONE
            }
        }
        return OkHttpClient.Builder()
            .connectTimeout(20, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS)
            .addInterceptor(
                DynamicBaseUrlInterceptor(
                    baseUrlProvider = { runBlocking { preferences.getBackendBaseUrl() } },
                ),
            )
            .addInterceptor(
                AuthInterceptor(
                    tokenProvider = { runBlocking { preferences.getAccessToken() } },
                    allowedHostsProvider = {
                        resolveBackendHosts(runBlocking { preferences.getBackendBaseUrl() })
                    },
                ),
            )
            .addInterceptor(logging)
            .build()
    }

    /**
     * Dedicated OkHttpClient for direct Cloudflare R2 presigned PUT uploads.
     * Deliberately omits DynamicBaseUrlInterceptor, AuthInterceptor, and URL/query logging
     * so presigned R2 host/signature/headers remain completely unmodified.
     */
    fun createR2UploadOkHttpClient(): OkHttpClient {
        return OkHttpClient.Builder()
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(120, TimeUnit.SECONDS)
            .writeTimeout(180, TimeUnit.SECONDS)
            .followRedirects(true)
            .followSslRedirects(true)
            .retryOnConnectionFailure(true)
            .build()
    }

    fun createApiService(
        baseUrl: String = BuildConfig.DEFAULT_BACKEND_BASE_URL,
        okHttpClient: OkHttpClient,
        moshi: Moshi,
    ): RailwayRulesApiService {
        val normalized = if (baseUrl.endsWith("/")) baseUrl else "$baseUrl/"
        return Retrofit.Builder()
            .baseUrl(normalized)
            .client(okHttpClient)
            .addConverterFactory(MoshiConverterFactory.create(moshi))
            .build()
            .create(RailwayRulesApiService::class.java)
    }
}
