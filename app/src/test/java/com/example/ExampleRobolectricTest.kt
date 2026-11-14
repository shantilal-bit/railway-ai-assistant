package com.example

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.example.data.local.DepartmentEntity
import com.example.data.local.DivisionEntity
import com.example.data.local.RailwayDatabase
import com.example.data.local.ZoneEntity
import com.example.data.remote.ChatAskResponseDto
import com.example.data.remote.NetworkModule
import com.example.data.remote.TaxonomyResponseDto
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
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
}
