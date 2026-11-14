package com.example.data.repository

import com.example.core.config.AppPreferences
import com.example.data.local.DepartmentEntity
import com.example.data.local.DivisionEntity
import com.example.data.local.RailwayDao
import com.example.data.local.RailwayDatabase
import com.example.data.local.ZoneEntity
import com.example.data.remote.RailwayRulesApiService
import com.example.domain.model.BackendHealth
import com.example.domain.model.RailwayDepartment
import com.example.domain.model.RailwayDivision
import com.example.domain.model.RailwayZone
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

class TaxonomyRepository(
    private val dao: RailwayDao,
    private val apiService: RailwayRulesApiService,
    private val preferences: AppPreferences,
) {
    val activeZones: Flow<List<RailwayZone>> = dao.observeActiveZones().map { list ->
        list.map { RailwayZone(it.id, it.code, it.name, it.nameHi, it.isActive, it.sortOrder) }
    }

    val allZones: Flow<List<RailwayZone>> = dao.observeAllZones().map { list ->
        list.map { RailwayZone(it.id, it.code, it.name, it.nameHi, it.isActive, it.sortOrder) }
    }

    fun divisionsForZone(zoneId: String): Flow<List<RailwayDivision>> =
        dao.observeDivisionsForZone(zoneId).map { list ->
            list.map {
                RailwayDivision(it.id, it.zoneId, it.code, it.name, it.nameHi, it.isActive, it.sortOrder)
            }
        }

    val activeDepartments: Flow<List<RailwayDepartment>> = dao.observeActiveDepartments().map { list ->
        list.map { RailwayDepartment(it.id, it.code, it.name, it.nameHi, it.isActive, it.sortOrder) }
    }

    suspend fun ensureSeeded() {
        RailwayDatabase.seedInitialTaxonomy(dao)
    }

    suspend fun syncFromBackend(includeInactiveZones: Boolean = true): Result<String> {
        return try {
            val dto = apiService.getTaxonomy(includeInactiveZones = includeInactiveZones)
            val zoneEntities = dto.zones.map {
                ZoneEntity(it.id, it.code, it.name, it.nameHi, it.isActive, it.sortOrder)
            }
            val divisionEntities = dto.divisions.map {
                DivisionEntity(it.id, it.zoneId, it.code, it.name, it.nameHi, it.isActive, it.sortOrder)
            }
            val deptEntities = dto.departments.map {
                DepartmentEntity(it.id, it.code, it.name, it.nameHi, it.isActive, it.sortOrder)
            }
            dao.replaceTaxonomy(zoneEntities, divisionEntities, deptEntities)
            Result.success(
                "Synced ${zoneEntities.count { it.isActive }} active zones, ${divisionEntities.size} divisions, ${deptEntities.size} departments",
            )
        } catch (e: Exception) {
            Result.failure(e)
        }
    }

    suspend fun checkBackendHealth(): BackendHealth {
        val url = preferences.getBackendBaseUrl()
        return try {
            val health = apiService.getHealth()
            BackendHealth(
                isConnected = health.status.equals("ok", ignoreCase = true),
                baseUrl = url,
                aiProvider = health.aiProvider,
                database = health.database,
                storage = health.storage,
                message = "Connected (${health.aiProvider ?: "backend"} • ${health.database ?: "pgvector"})",
            )
        } catch (e: Exception) {
            BackendHealth(
                isConnected = false,
                baseUrl = url,
                message = e.localizedMessage ?: "Backend server unreachable",
            )
        }
    }
}
