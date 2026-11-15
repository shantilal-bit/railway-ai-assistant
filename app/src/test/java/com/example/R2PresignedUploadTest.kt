package com.example

import android.content.Context
import android.net.Uri
import androidx.test.core.app.ApplicationProvider
import com.example.data.remote.AdminDocumentDto
import com.example.data.remote.AuthInterceptor
import com.example.data.remote.AuthSessionResponseDto
import com.example.data.remote.ChatAskRequestDto
import com.example.data.remote.ChatAskResponseDto
import com.example.data.remote.DocumentStatusUpdateDto
import com.example.data.remote.DynamicBaseUrlInterceptor
import com.example.data.remote.HealthResponseDto
import com.example.data.remote.ImportDrivePdfRequestDto
import com.example.data.remote.LoginRequestDto
import com.example.data.remote.NetworkModule
import com.example.data.remote.PresignUploadRequestDto
import com.example.data.remote.PresignUploadResponseDto
import com.example.data.remote.RailwayRulesApiService
import com.example.data.remote.RegisterDocumentRequestDto
import com.example.data.remote.ReprocessDocumentRequestDto
import com.example.data.remote.SignupRequestDto
import com.example.data.remote.SignupResponseDto
import com.example.data.remote.TaxonomyResponseDto
import com.example.data.repository.AdminRepository
import kotlinx.coroutines.runBlocking
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36])
class R2PresignedUploadTest {

    @Test
    fun `createR2UploadOkHttpClient has no backend interceptors and supports redirects`() {
        val client = NetworkModule.createR2UploadOkHttpClient()
        assertTrue(client.interceptors.isEmpty())
        assertTrue(client.networkInterceptors.isEmpty())
        assertTrue(client.followRedirects)
        assertTrue(client.followSslRedirects)
    }

    @Test
    fun `DynamicBaseUrlInterceptor and AuthInterceptor rewrite backend calls only and leave R2 URL untouched`() {
        val capturedRequests = mutableListOf<Request>()
        val backendClient = OkHttpClient.Builder()
            .addInterceptor(
                DynamicBaseUrlInterceptor(
                    baseUrlProvider = { "https://custom-backend.example.com/" },
                    defaultBaseUrlProvider = { "https://railway-rules-backend.onrender.com/" },
                ),
            )
            .addInterceptor(
                AuthInterceptor(
                    tokenProvider = { "secret-jwt-token" },
                    allowedHostsProvider = {
                        NetworkModule.resolveBackendHosts(
                            configuredBaseUrl = "https://custom-backend.example.com/",
                            defaultBaseUrl = "https://railway-rules-backend.onrender.com/",
                        )
                    },
                ),
            )
            .addInterceptor { chain ->
                val req = chain.request()
                capturedRequests.add(req)
                Response.Builder()
                    .request(req)
                    .protocol(Protocol.HTTP_1_1)
                    .code(200)
                    .message("OK")
                    .body("{}".toResponseBody("application/json".toMediaType()))
                    .build()
            }
            .build()

        // 1. Backend API call MUST rewrite host and add Authorization header
        backendClient.newCall(
            Request.Builder()
                .url("https://railway-rules-backend.onrender.com/v1/admin/documents/presign-upload")
                .post("{}".toRequestBody("application/json".toMediaType()))
                .build(),
        ).execute().close()

        val backendReq = capturedRequests[0]
        assertEquals("custom-backend.example.com", backendReq.url.host)
        assertEquals("/v1/admin/documents/presign-upload", backendReq.url.encodedPath)
        assertEquals("Bearer secret-jwt-token", backendReq.header("Authorization"))

        // 2. Presigned R2 URL MUST keep R2 host/query untouched and NEVER attach Backend Bearer token
        val r2Url = "https://acct123.r2.cloudflarestorage.com/railway-rules-pdfs/wr/bct/opt/rule.pdf?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-SignedHeaders=content-type%3Bhost&X-Amz-Signature=deadbeef"
        backendClient.newCall(
            Request.Builder()
                .url(r2Url)
                .header("Content-Type", "application/pdf")
                .put("%PDF-1.7\n...".toByteArray().toRequestBody("application/pdf".toMediaType()))
                .build(),
        ).execute().close()

        val r2Req = capturedRequests[1]
        assertEquals(r2Url, r2Req.url.toString())
        assertEquals("acct123.r2.cloudflarestorage.com", r2Req.url.host)
        assertNull(r2Req.header("Authorization"))
    }

    @Test
    fun `AdminRepository uploadPdfAndRegister sends unaltered PUT to R2 without Authorization and registers doc`() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val tempPdf = File(context.cacheDir, "test_gr_sr.pdf").apply {
            writeBytes("%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\n".toByteArray(Charsets.US_ASCII))
        }
        try {
            val presignedUrl =
                "https://acct999.r2.cloudflarestorage.com/railway-rules-pdfs/wr/bct/opt/rule.pdf" +
                    "?X-Amz-Algorithm=AWS4-HMAC-SHA256" +
                    "&X-Amz-Credential=abc%2F20261115%2Fauto%2Fs3%2Faws4_request" +
                    "&X-Amz-Date=20261115T120000Z" +
                    "&X-Amz-Expires=900" +
                    "&X-Amz-SignedHeaders=content-type%3Bhost" +
                    "&X-Amz-Signature=0123456789abcdef"

            var capturedR2Request: Request? = null
            var capturedRegisterRequest: RegisterDocumentRequestDto? = null

            val fakeR2Client = NetworkModule.createR2UploadOkHttpClient()
                .newBuilder()
                .addInterceptor { chain ->
                    val req = chain.request()
                    capturedR2Request = req
                    Response.Builder()
                        .request(req)
                        .protocol(Protocol.HTTP_1_1)
                        .code(200)
                        .message("OK")
                        .body("".toResponseBody(null))
                        .build()
                }
                .build()

            val fakeApi = object : FakeRailwayRulesApiService() {
                override suspend fun presignPdfUpload(request: PresignUploadRequestDto): PresignUploadResponseDto {
                    return PresignUploadResponseDto(
                        objectKey = "wr/bct/opt/rule.pdf",
                        presignedPutUrl = presignedUrl,
                    )
                }

                override suspend fun registerDocument(request: RegisterDocumentRequestDto): AdminDocumentDto {
                    capturedRegisterRequest = request
                    return AdminDocumentDto(
                        id = "42",
                        title = request.title,
                        documentNumber = request.documentNumber,
                        documentType = request.documentType,
                        issuingAuthority = request.issuingAuthority,
                        authorityRank = request.authorityRank ?: 85,
                        status = "draft",
                        ingestionStatus = "processing",
                    )
                }
            }

            val repo = AdminRepository(apiService = fakeApi, r2OkHttpClient = fakeR2Client)
            val result = repo.uploadPdfAndRegister(
                contentResolver = context.contentResolver,
                pdfUri = Uri.fromFile(tempPdf),
                fileName = "rule.pdf",
                title = "WR G&SR 2024",
                documentNumber = "WR-GSR-2024",
                documentType = "RULE_BOOK",
                issuingAuthority = "Western Railway",
                authorityRank = 85,
                scopeLevel = "DEPARTMENT",
                zoneId = "1",
                zoneCode = "WR",
                divisionId = "11",
                divisionCode = "BCT",
                departmentId = "101",
                departmentCode = "OPT",
                issueDate = null,
                effectiveDate = null,
                requiresOcr = false,
                supersedesDocumentId = null,
            )

            assertTrue(result.isSuccess)
            assertEquals("42", result.getOrNull()?.id)
            assertEquals("PUT", capturedR2Request?.method)
            assertEquals(presignedUrl, capturedR2Request?.url?.toString())
            assertEquals("acct999.r2.cloudflarestorage.com", capturedR2Request?.url?.host)
            assertEquals("application/pdf", capturedR2Request?.header("Content-Type"))
            assertEquals("application/pdf", capturedR2Request?.body?.contentType().toString())
            assertNull(capturedR2Request?.header("Authorization"))
            assertEquals("wr/bct/opt/rule.pdf", capturedRegisterRequest?.objectKey)
        } finally {
            tempPdf.delete()
        }
    }

    @Test
    fun `AdminRepository does not expose presigned signature in upload error message`() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val tempPdf = File(context.cacheDir, "test_err.pdf").apply {
            writeBytes("%PDF-1.7\n%test".toByteArray(Charsets.US_ASCII))
        }
        try {
            val presignedUrl =
                "https://acct999.r2.cloudflarestorage.com/railway-rules-pdfs/wr/rule.pdf?X-Amz-Signature=supersecret999"
            val fakeR2Client = NetworkModule.createR2UploadOkHttpClient()
                .newBuilder()
                .addInterceptor { chain ->
                    Response.Builder()
                        .request(chain.request())
                        .protocol(Protocol.HTTP_1_1)
                        .code(403)
                        .message("Forbidden")
                        .body("".toResponseBody(null))
                        .build()
                }
                .build()

            val fakeApi = object : FakeRailwayRulesApiService() {
                override suspend fun presignPdfUpload(request: PresignUploadRequestDto): PresignUploadResponseDto {
                    return PresignUploadResponseDto(
                        objectKey = "wr/rule.pdf",
                        presignedPutUrl = presignedUrl,
                    )
                }
            }

            val repo = AdminRepository(apiService = fakeApi, r2OkHttpClient = fakeR2Client)
            val result = repo.uploadPdfAndRegister(
                contentResolver = context.contentResolver,
                pdfUri = Uri.fromFile(tempPdf),
                fileName = "rule.pdf",
                title = "Test Doc",
                documentNumber = null,
                documentType = "CIRCULAR",
                issuingAuthority = "WR",
                authorityRank = 70,
                scopeLevel = "ZONE",
                zoneId = "1",
                zoneCode = "WR",
                divisionId = null,
                divisionCode = null,
                departmentId = null,
                departmentCode = null,
                issueDate = null,
                effectiveDate = null,
                requiresOcr = false,
                supersedesDocumentId = null,
            )

            assertTrue(result.isFailure)
            val message = result.exceptionOrNull()?.message.orEmpty()
            assertTrue(message.contains("HTTP 403"))
            assertTrue(message.contains("acct999.r2.cloudflarestorage.com"))
            assertFalse(message.contains("supersecret999"))
        } finally {
            tempPdf.delete()
        }
    }

    private open class FakeRailwayRulesApiService : RailwayRulesApiService {
        override suspend fun getHealth(): HealthResponseDto = throw UnsupportedOperationException()
        override suspend fun getTaxonomy(includeInactiveZones: Boolean): TaxonomyResponseDto = throw UnsupportedOperationException()
        override suspend fun login(request: LoginRequestDto): AuthSessionResponseDto = throw UnsupportedOperationException()
        override suspend fun signup(request: SignupRequestDto): SignupResponseDto = throw UnsupportedOperationException()
        override suspend fun askRule(request: ChatAskRequestDto): ChatAskResponseDto = throw UnsupportedOperationException()
        override suspend fun listAdminDocuments(search: String?): List<AdminDocumentDto> = emptyList()
        override suspend fun presignPdfUpload(request: PresignUploadRequestDto): PresignUploadResponseDto = throw UnsupportedOperationException()
        override suspend fun registerDocument(request: RegisterDocumentRequestDto): AdminDocumentDto = throw UnsupportedOperationException()
        override suspend fun importDrivePdf(request: ImportDrivePdfRequestDto): AdminDocumentDto = throw UnsupportedOperationException()
        override suspend fun reprocessDocument(documentId: String, body: ReprocessDocumentRequestDto): AdminDocumentDto = throw UnsupportedOperationException()
        override suspend fun updateDocumentStatus(documentId: String, body: DocumentStatusUpdateDto): AdminDocumentDto = throw UnsupportedOperationException()
    }
}
