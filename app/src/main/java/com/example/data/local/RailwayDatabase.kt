package com.example.data.local

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.sqlite.db.SupportSQLiteDatabase
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

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
        const val WR_ZONE_ID = "wr-zone-001"

        fun create(context: Context, scope: CoroutineScope): RailwayDatabase {
            lateinit var db: RailwayDatabase
            db = Room.databaseBuilder(
                context.applicationContext,
                RailwayDatabase::class.java,
                "railway_rules.db",
            )
                .addCallback(object : Callback() {
                    override fun onCreate(sqliteDb: SupportSQLiteDatabase) {
                        super.onCreate(sqliteDb)
                        scope.launch(Dispatchers.IO) {
                            seedInitialTaxonomy(db.railwayDao())
                        }
                    }
                })
                .build()
            return db
        }

        /**
         * Seeds ONLY the structural Western Railway taxonomy (Zone, 6 Divisions, 13 Departments)
         * so the opening selector works immediately offline and updates seamlessly from Supabase/Backend.
         * Never seeds fake Railway rules or fabricated answers.
         */
        suspend fun seedInitialTaxonomy(dao: RailwayDao) {
            if (dao.getZoneCount() > 0) return

            val zones = listOf(
                ZoneEntity(
                    id = WR_ZONE_ID,
                    code = "WR",
                    name = "Western Railway",
                    nameHi = "पश्चिम रेलवे",
                    isActive = true,
                    sortOrder = 1,
                ),
            )

            val divisions = listOf(
                DivisionEntity("wr-div-bct", WR_ZONE_ID, "BCT", "Mumbai Central", "मुंबई सेंट्रल", true, 1),
                DivisionEntity("wr-div-brc", WR_ZONE_ID, "BRC", "Vadodara", "वडोदरा", true, 2),
                DivisionEntity("wr-div-adi", WR_ZONE_ID, "ADI", "Ahmedabad", "अहमदाबाद", true, 3),
                DivisionEntity("wr-div-rtm", WR_ZONE_ID, "RTM", "Ratlam", "रतलाम", true, 4),
                DivisionEntity("wr-div-rjt", WR_ZONE_ID, "RJT", "Rajkot", "राजकोट", true, 5),
                DivisionEntity("wr-div-bvp", WR_ZONE_ID, "BVP", "Bhavnagar", "भावनगर", true, 6),
            )

            val departments = listOf(
                DepartmentEntity("dept-eng", "ENG", "Engineering", "इंजीनियरिंग", true, 1),
                DepartmentEntity("dept-opt", "OPT", "Operating", "परिचालन", true, 2),
                DepartmentEntity("dept-com", "COM", "Commercial", "वाणिज्य", true, 3),
                DepartmentEntity("dept-per", "PER", "Personnel", "कार्मिक", true, 4),
                DepartmentEntity("dept-ele", "ELE", "Electrical", "विद्युत", true, 5),
                DepartmentEntity("dept-mec", "MEC", "Mechanical", "यांत्रिक", true, 6),
                DepartmentEntity("dept-snt", "SNT", "Signal & Telecommunication", "सिग्नल एवं दूरसंचार", true, 7),
                DepartmentEntity("dept-acc", "ACC", "Accounts", "लेखा", true, 8),
                DepartmentEntity("dept-str", "STR", "Stores", "भंडार", true, 9),
                DepartmentEntity("dept-med", "MED", "Medical", "चिकित्सा", true, 10),
                DepartmentEntity("dept-saf", "SAF", "Safety", "संरक्षा", true, 11),
                DepartmentEntity("dept-rpf", "RPF", "Security (RPF)", "सुरक्षा (आरपीएफ)", true, 12),
                DepartmentEntity("dept-oth", "OTH", "Other", "अन्य", true, 13),
            )

            dao.replaceTaxonomy(zones, divisions, departments)
        }
    }
}
