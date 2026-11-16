package com.example.data.remote

import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

interface RailwayRulesApiService {

    @GET("v1/health")
    suspend fun getHealth(): HealthResponseDto

    @GET("v1/taxonomy")
    suspend fun getTaxonomy(
        @Query("includeInactiveZones") includeInactiveZones: Boolean = false,
    ): TaxonomyResponseDto

    @POST("v1/auth/login")
    suspend fun login(@Body request: LoginRequestDto): AuthSessionResponseDto

    @POST("v1/auth/signup")
    suspend fun signup(@Body request: SignupRequestDto): SignupResponseDto

    @POST("v1/auth/refresh")
    suspend fun refreshSession(@Body request: RefreshTokenRequestDto): AuthSessionResponseDto

    @POST("v1/chat/ask")
    suspend fun askRule(@Body request: ChatAskRequestDto): ChatAskResponseDto

    @GET("v1/admin/documents")
    suspend fun listAdminDocuments(
        @Query("search") search: String? = null,
    ): List<AdminDocumentDto>

    @POST("v1/admin/documents/presign-upload")
    suspend fun presignPdfUpload(@Body request: PresignUploadRequestDto): PresignUploadResponseDto

    @POST("v1/admin/documents")
    suspend fun registerDocument(@Body request: RegisterDocumentRequestDto): AdminDocumentDto

    @POST("v1/admin/documents/import-drive")
    suspend fun importDrivePdf(@Body request: ImportDrivePdfRequestDto): AdminDocumentDto

    @POST("v1/admin/documents/{id}/reprocess")
    suspend fun reprocessDocument(
        @Path("id") documentId: String,
        @Body body: ReprocessDocumentRequestDto,
    ): AdminDocumentDto

    @PATCH("v1/admin/documents/{id}/status")
    suspend fun updateDocumentStatus(
        @Path("id") documentId: String,
        @Body body: DocumentStatusUpdateDto,
    ): AdminDocumentDto
}
