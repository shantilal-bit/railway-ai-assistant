package com.example.data.local

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase

@Database(
    entities = [
        ZoneEntity::class,
        DivisionEntity::class,
        DepartmentEntity::class,
        ChatSessionEntity::class,
        ChatMessageEntity::class,
    ],
    version = 1,
    exportSchema = false,
)
abstract class RailwayDatabase : RoomDatabase() {
    abstract fun railwayDao(): RailwayDao

    companion object {
        fun create(context: Context): RailwayDatabase {
            return Room.databaseBuilder(
                context.applicationContext,
                RailwayDatabase::class.java,
                "railway_rules.db",
            ).build()
        }
    }
}
