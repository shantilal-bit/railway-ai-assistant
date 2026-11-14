package com.example

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.example.data.local.DepartmentEntity
import com.example.data.local.DivisionEntity
import com.example.data.local.RailwayDatabase
import com.example.data.local.ZoneEntity
import com.example.data.remote.AdminDocumentDto
import com.example.data.remote.ChatAskResponseDto
import com.example.data.remote.ImportDrivePdfRequestDto
import com.example.data.remote.NetworkModule
import com.example.data.remote.TaxonomyResponseDto
import com.example.data.repository.AdminRepository
import com.example.domain.model.ScopeLevel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [36])
class ExampleRobolectricTest {

    @Test
    fun `app name matches Railway Rules AI Assistant`() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val appName = context.getString(R.string.app_name)
        assertEquals("Railway Rules AI Assistant", appName)
    }

    @Test
    fun `replaceTaxonomy deletes old rows and inserts backend records respecting foreign keys`() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val db = Room.inMemoryDatabaseBuilder(context, RailwayDatabase::class.java)
            .allowMainThreadQueries()
            .build()
        try {
            val dao = db.railwayDao()

            // Initially database has no hardcoded taxonomy
            assertTrue(dao.observeActiveZones().first().isEmpty())

            // Insert initial synced records with stringified bigint IDs
            dao.replaceTaxonomy(
                zones = listOf(ZoneEntity("1", "OLD", "Old Zone", null, true, 1)),
                divisions = listOf(DivisionEntity("10", "1", "OLD_DIV", "Old Division", null, true, 1)),
                departments = listOf(DepartmentEntity("100", "OLD_DEPT", "Old Dept", null, true, 1)),
            )

            // Replace with new backend records
            dao.replaceTaxonomy(
                zones = listOf(ZoneEntity("2", "WR", "Western Railway", "पश्चिम रेलवे", true, 1)),
                divisions = listOf(DivisionEntity("21", "2", "BCT", "Mumbai Central", "मुंबई सेंट्रल", true, 1)),
                departments = listOf(DepartmentEntity("201", "OPT", "Operating", "परिचालन", true, 1)),
            )

            val zones = dao.observeActiveZones().first()
            assertEquals(1, zones.size)
            assertEquals("2", zones.first().id)

            val oldDivisions = dao.observeDivisionsForZone("1").first()
            assertTrue(oldDivisions.isEmpty())

            val newDivisions = dao.observeDivisionsForZone("2").first()
            assertEquals(1, newDivisions.size)
            assertEquals("21", newDivisions.first().id)
            assertEquals("2", newDivisions.first().zoneId)

            val departments = dao.observeActiveDepartments().first()
            assertEquals(1, departments.size)
            assertEquals("201", departments.first().id)
        } finally {
            db.close()
        }
    }

    @Test
    fun `moshi parses stringified bigint taxonomy response`() {
        val moshi = NetworkModule.createMoshi()
        val adapter = moshi.adapter(TaxonomyResponseDto::class.java)
        val json = """
            {
              "zones": [
                {"id": "1", "code": "WR", "name": "Western Railway", "name_hi": "पश्चिम रेलवे", "is_active": true, "sort_order": 1}
              ],
              "divisions": [
                {"id": "11", "zone_id": "1", "code": "BCT", "name": "Mumbai Central", "name_hi": null, "is_active": true, "sort_order": 1}
              ],
              "departments": [
                {"id": "101", "code": "OPT", "name": "Operating", "name_hi": null, "is_active": true, "sort_order": 1}
              ]
            }
        """.trimIndent()
        val parsed = adapter.fromJson(json)
        assertNotNull(parsed)
        assertEquals("1", parsed?.zones?.first()?.id)
        assertEquals("1", parsed?.divisions?.first()?.zoneId)
        assertEquals("101", parsed?.departments?.first()?.id)
    }

    @Test
    fun `moshi parses 7-part structured rule response`() {
        val moshi = NetworkModule.createMoshi()
        val adapter = moshi.adapter(ChatAskResponseDto::class.java)
        val json = """
            {
              "responseLanguage": "en",
              "isReliableAnswerFound": true,
              "directAnswer": "Test direct answer",
              "detailedExplanation": "Detailed explanation text",
              "applicableRuleNumber": "Rule 4.10",
              "officialDocumentName": "G&SR Western Railway",
              "pdfPageNumber": "42",
              "amendmentOrCircularRef": "AS-12",
              "effectiveDate": "2024-04-01",
              "conflictWarning": null,
              "aiProvider": "groq",
              "modelName": "llama-3.3-70b-versatile",
              "citations": []
            }
        """.trimIndent()
        val parsed = adapter.fromJson(json)
        assertNotNull(parsed)
        assertEquals("Rule 4.10", parsed?.applicableRuleNumber)
        assertEquals("42", parsed?.pdfPageNumber)
        assertEquals("groq", parsed?.aiProvider)
    }

    @Test
    fun `moshi parses AdminDocumentDto with RAG ingestion status, chunk count, and error fields`() {
        val moshi = NetworkModule.createMoshi()
        val adapter = moshi.adapter(AdminDocumentDto::class.java)
        val json = """
            {
              "id": "doc-123",
              "title": "RBE 45/2024 Leave Circular",
              "document_number": "RBE 45/2024",
              "document_type": "CIRCULAR",
              "issuing_authority": "Railway Board",
              "authority_rank": 100,
              "status": "draft",
              "issue_date": "2024-05-01",
              "effective_date": "2024-06-01",
              "requires_ocr": true,
              "ocr_status": "failed",
              "ingestion_status": "failed",
              "ingestion_error": "No extractable text found",
              "chunk_count": 0,
              "indexed_at": null,
              "source_type": "google_drive",
              "source_url": "https://drive.google.com/file/d/abc123456789/view",
              "page_count": 12
            }
        """.trimIndent()
        val parsed = adapter.fromJson(json)
        assertNotNull(parsed)
        assertEquals(100, parsed?.authorityRank)
        assertEquals("failed", parsed?.ingestionStatus)
        assertEquals("No extractable text found", parsed?.ingestionError)
        assertEquals("google_drive", parsed?.sourceType)
        assertEquals(12, parsed?.pageCount)
    }

    @Test
    fun `AdminRepository validates PDF magic signature and non-empty bytes`() {
        AdminRepository.validatePdfBytes("%PDF-1.7\n%...".toByteArray(Charsets.US_ASCII))

        assertThrows(IllegalArgumentException::class.java) {
            AdminRepository.validatePdfBytes(ByteArray(0))
        }
        assertThrows(IllegalArgumentException::class.java) {
            AdminRepository.validatePdfBytes("<html>not a pdf</html>".toByteArray(Charsets.US_ASCII))
        }
    }

    @Test
    fun `ImportDrivePdfRequestDto serializes scopeLevel and authorityRank`() {
        val moshi = NetworkModule.createMoshi()
        val adapter = moshi.adapter(ImportDrivePdfRequestDto::class.java)
        val req = ImportDrivePdfRequestDto(
            driveUrl = "https://drive.google.com/file/d/1234567890abcdef/view",
            title = "G&SR WR",
            documentType = "RULE_BOOK",
            issuingAuthority = "Railway Board",
            authorityRank = 100,
            scopeLevel = ScopeLevel.RAILWAY_BOARD.apiValue,
            zoneCode = "WR",
        )
        val json = adapter.toJson(req)
        assertTrue(json.contains("\"scopeLevel\":\"RAILWAY_BOARD\""))
        assertTrue(json.contains("\"authorityRank\":100"))
    }
}
