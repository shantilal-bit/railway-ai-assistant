package com.example.data.local

import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(tableName = "zones")
data class ZoneEntity(
    @PrimaryKey val id: String,
    val code: String,
    val name: String,
    val nameHi: String?,
    val isActive: Boolean,
    val sortOrder: Int,
)

@Entity(
    tableName = "divisions",
    foreignKeys = [
        ForeignKey(
            entity = ZoneEntity::class,
            parentColumns = ["id"],
            childColumns = ["zoneId"],
            onDelete = ForeignKey.CASCADE,
        ),
    ],
    indices = [Index("zoneId")],
)
data class DivisionEntity(
    @PrimaryKey val id: String,
    val zoneId: String,
    val code: String,
    val name: String,
    val nameHi: String?,
    val isActive: Boolean,
    val sortOrder: Int,
)

@Entity(tableName = "departments")
data class DepartmentEntity(
    @PrimaryKey val id: String,
    val code: String,
    val name: String,
    val nameHi: String?,
    val isActive: Boolean,
    val sortOrder: Int,
)

@Entity(tableName = "chat_sessions")
data class ChatSessionEntity(
    @PrimaryKey val id: String,
    val title: String,
    val zoneId: String,
    val zoneName: String,
    val divisionId: String,
    val divisionName: String,
    val departmentId: String,
    val departmentName: String,
    val updatedAtMillis: Long,
)

@Entity(
    tableName = "chat_messages",
    foreignKeys = [
        ForeignKey(
            entity = ChatSessionEntity::class,
            parentColumns = ["id"],
            childColumns = ["sessionId"],
            onDelete = ForeignKey.CASCADE,
        ),
    ],
    indices = [Index("sessionId")],
)
data class ChatMessageEntity(
    @PrimaryKey val id: String,
    val sessionId: String,
    val sender: String,
    val text: String,
    val language: String,
    val structuredAnswerJson: String?,
    val createdAtMillis: Long,
)
