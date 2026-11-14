package com.example

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.example.data.local.RailwayDatabase
import com.example.data.remote.ChatAskResponseDto
import com.example.data.remote.NetworkModule
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
    fun `database seeds Western Railway with 6 divisions and 13 departments`() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<Context>()
        val db = Room.inMemoryDatabaseBuilder(context, RailwayDatabase::class.java)
            .allowMainThreadQueries()
            .build()
        try {
            val dao = db.railwayDao()
            RailwayDatabase.seedInitialTaxonomy(dao)

            val zones = dao.observeActiveZones().first()
            assertEquals(1, zones.size)
            assertEquals("WR", zones.first().code)
            assertEquals("Western Railway", zones.first().name)

            val divisions = dao.observeDivisionsForZone(zones.first().id).first()
            assertEquals(
                listOf("Mumbai Central", "Vadodara", "Ahmedabad", "Ratlam", "Rajkot", "Bhavnagar"),
                divisions.map { it.name },
            )

            val departments = dao.observeActiveDepartments().first()
            assertEquals(13, departments.size)
            assertTrue(departments.any { it.name == "Signal & Telecommunication" })
            assertTrue(departments.any { it.name == "Security (RPF)" })
        } finally {
            db.close()
        }
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
