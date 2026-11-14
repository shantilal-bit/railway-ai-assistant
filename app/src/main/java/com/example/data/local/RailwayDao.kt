package com.example.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import kotlinx.coroutines.flow.Flow

@Dao
interface RailwayDao {

    @Query("SELECT * FROM zones WHERE isActive = 1 ORDER BY sortOrder ASC")
    fun observeActiveZones(): Flow<List<ZoneEntity>>

    @Query("SELECT * FROM zones ORDER BY sortOrder ASC")
    fun observeAllZones(): Flow<List<ZoneEntity>>

    @Query("SELECT * FROM divisions WHERE zoneId = :zoneId AND isActive = 1 ORDER BY sortOrder ASC")
    fun observeDivisionsForZone(zoneId: String): Flow<List<DivisionEntity>>

    @Query("SELECT * FROM departments WHERE isActive = 1 ORDER BY sortOrder ASC")
    fun observeActiveDepartments(): Flow<List<DepartmentEntity>>

    @Query("SELECT COUNT(*) FROM zones")
    suspend fun getZoneCount(): Int

    @Query("DELETE FROM divisions")
    suspend fun deleteAllDivisions()

    @Query("DELETE FROM departments")
    suspend fun deleteAllDepartments()

    @Query("DELETE FROM zones")
    suspend fun deleteAllZones()

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertZones(zones: List<ZoneEntity>)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertDivisions(divisions: List<DivisionEntity>)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertDepartments(departments: List<DepartmentEntity>)

    @Transaction
    suspend fun replaceTaxonomy(
        zones: List<ZoneEntity>,
        divisions: List<DivisionEntity>,
        departments: List<DepartmentEntity>,
    ) {
        deleteAllDivisions()
        deleteAllDepartments()
        deleteAllZones()
        upsertZones(zones)
        upsertDivisions(divisions)
        upsertDepartments(departments)
    }

    @Query("SELECT * FROM chat_sessions ORDER BY updatedAtMillis DESC")
    fun observeChatSessions(): Flow<List<ChatSessionEntity>>

    @Query("SELECT * FROM chat_sessions WHERE id = :sessionId LIMIT 1")
    suspend fun getSessionById(sessionId: String): ChatSessionEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsertSession(session: ChatSessionEntity)

    @Query("DELETE FROM chat_sessions WHERE id = :sessionId")
    suspend fun deleteSession(sessionId: String)

    @Query("SELECT * FROM chat_messages WHERE sessionId = :sessionId ORDER BY createdAtMillis ASC")
    fun observeMessagesForSession(sessionId: String): Flow<List<ChatMessageEntity>>

    @Query("SELECT * FROM chat_messages WHERE sessionId = :sessionId ORDER BY createdAtMillis ASC")
    suspend fun getMessagesForSession(sessionId: String): List<ChatMessageEntity>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertMessage(message: ChatMessageEntity)
}
