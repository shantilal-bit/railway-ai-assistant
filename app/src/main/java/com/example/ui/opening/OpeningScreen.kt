package com.example.ui.opening

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowForward
import androidx.compose.material.icons.filled.AccountBalance
import androidx.compose.material.icons.filled.AdminPanelSettings
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Build
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.CloudDone
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material.icons.filled.Construction
import androidx.compose.material.icons.filled.DirectionsRailway
import androidx.compose.material.icons.filled.ElectricBolt
import androidx.compose.material.icons.filled.Engineering
import androidx.compose.material.icons.filled.Groups
import androidx.compose.material.icons.filled.HealthAndSafety
import androidx.compose.material.icons.filled.Inventory2
import androidx.compose.material.icons.filled.Layers
import androidx.compose.material.icons.filled.LocalHospital
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.ReceiptLong
import androidx.compose.material.icons.filled.Security
import androidx.compose.material.icons.filled.SettingsInputAntenna
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material.icons.filled.Train
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.example.R
import com.example.domain.model.RailwayDepartment
import com.example.domain.model.RailwayDivision
import com.example.domain.model.RailwayZone
import com.example.domain.model.UserRole
import com.example.ui.components.SearchHierarchySheet
import com.example.ui.components.ServerConnectionDialog
import com.example.ui.theme.DevanagariFontFamily
import com.example.ui.theme.RailBrass
import com.example.ui.theme.RailNavyDeep
import com.example.ui.theme.RailSignalGreen
import com.example.ui.theme.RailSignalGreenContainer

@OptIn(ExperimentalLayoutApi::class, ExperimentalMaterial3Api::class)
@Composable
fun OpeningScreen(
    viewModel: OpeningViewModel,
    onOpenChat: (RailwayZone, RailwayDivision, RailwayDepartment) -> Unit,
    onOpenAccount: () -> Unit,
    onOpenAdmin: () -> Unit,
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    var showServerDialog by remember { mutableStateOf(false) }
    var showHierarchySheet by remember { mutableStateOf(false) }
    var zoneMenuExpanded by remember { mutableStateOf(false) }

    if (showServerDialog) {
        ServerConnectionDialog(
            currentBaseUrl = state.backendBaseUrl,
            health = state.backendHealth,
            onSaveAndTest = { viewModel.updateBackendBaseUrl(it) },
            onDismiss = { showServerDialog = false },
        )
    }

    if (showHierarchySheet) {
        SearchHierarchySheet(onDismiss = { showHierarchySheet = false })
    }

    Scaffold(
        contentWindowInsets = WindowInsets.safeDrawing,
        containerColor = MaterialTheme.colorScheme.background,
        bottomBar = {
            Surface(
                tonalElevation = 3.dp,
                shadowElevation = 6.dp,
                color = MaterialTheme.colorScheme.surface,
            ) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .navigationBarsPadding()
                        .padding(horizontal = 16.dp, vertical = 12.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Column(
                        modifier = Modifier.widthIn(max = 640.dp).fillMaxWidth(),
                        verticalArrangement = Arrangement.spacedBy(6.dp),
                    ) {
                        if (state.canProceedToChat) {
                            Text(
                                text = "${state.selectedZone?.code} • ${state.selectedDivision?.name} • ${state.selectedDepartment?.name}",
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.primary,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                        }
                        Button(
                            onClick = {
                                val z = state.selectedZone
                                val d = state.selectedDivision
                                val dept = state.selectedDepartment
                                if (z != null && d != null && dept != null) {
                                    viewModel.persistSelection()
                                    onOpenChat(z, d, dept)
                                }
                            },
                            enabled = state.canProceedToChat,
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(52.dp)
                                .testTag("open_chat_button"),
                            shape = MaterialTheme.shapes.medium,
                            colors = ButtonDefaults.buttonColors(
                                containerColor = MaterialTheme.colorScheme.primary,
                            ),
                        ) {
                            Text(
                                text = stringResource(R.string.cta_open_chat),
                                style = MaterialTheme.typography.labelLarge,
                            )
                            Spacer(modifier = Modifier.width(8.dp))
                            Icon(
                                imageVector = Icons.AutoMirrored.Filled.ArrowForward,
                                contentDescription = null,
                            )
                        }
                    }
                }
            }
        },
    ) { innerPadding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding),
            contentAlignment = Alignment.TopCenter,
        ) {
            Column(
                modifier = Modifier
                    .widthIn(max = 640.dp)
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 16.dp, vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                // Hero Railway Header Card
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(176.dp)
                        .clip(MaterialTheme.shapes.large),
                ) {
                    Image(
                        painter = painterResource(id = R.drawable.img_railway_banner),
                        contentDescription = "Indian Railway concourse and express train banner",
                        contentScale = ContentScale.Crop,
                        modifier = Modifier.fillMaxSize(),
                    )
                    Box(
                        modifier = Modifier
                            .fillMaxSize()
                            .background(
                                Brush.horizontalGradient(
                                    colors = listOf(
                                        RailNavyDeep.copy(alpha = 0.94f),
                                        RailNavyDeep.copy(alpha = 0.78f),
                                        RailNavyDeep.copy(alpha = 0.45f),
                                    ),
                                ),
                            ),
                    )
                    // Brass rail accent bar at bottom of hero
                    Box(
                        modifier = Modifier
                            .align(Alignment.BottomCenter)
                            .fillMaxWidth()
                            .height(4.dp)
                            .background(RailBrass),
                    )
                    Column(
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(18.dp),
                        verticalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Surface(
                                shape = RoundedCornerShape(999.dp),
                                color = Color.White.copy(alpha = 0.16f),
                            ) {
                                Row(
                                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Icon(
                                        imageVector = Icons.Filled.DirectionsRailway,
                                        contentDescription = null,
                                        tint = RailBrass,
                                        modifier = Modifier.size(16.dp),
                                    )
                                    Spacer(modifier = Modifier.width(6.dp))
                                    Text(
                                        text = "INDIAN RAILWAYS",
                                        style = MaterialTheme.typography.labelSmall,
                                        color = Color.White,
                                    )
                                }
                            }

                            Surface(
                                shape = RoundedCornerShape(999.dp),
                                color = if (state.backendHealth?.isConnected == true) {
                                    RailSignalGreenContainer
                                } else {
                                    Color.White.copy(alpha = 0.18f)
                                },
                                modifier = Modifier
                                    .clickable { showServerDialog = true }
                                    .testTag("server_status_badge"),
                            ) {
                                Row(
                                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Icon(
                                        imageVector = if (state.backendHealth?.isConnected == true) {
                                            Icons.Filled.CloudDone
                                        } else {
                                            Icons.Filled.CloudOff
                                        },
                                        contentDescription = "Backend server status",
                                        tint = if (state.backendHealth?.isConnected == true) {
                                            RailSignalGreen
                                        } else {
                                            Color.White
                                        },
                                        modifier = Modifier.size(14.dp),
                                    )
                                    Spacer(modifier = Modifier.width(5.dp))
                                    Text(
                                        text = if (state.backendHealth?.isConnected == true) {
                                            "API Online"
                                        } else {
                                            "Server Setup"
                                        },
                                        style = MaterialTheme.typography.labelSmall,
                                        color = if (state.backendHealth?.isConnected == true) {
                                            RailSignalGreen
                                        } else {
                                            Color.White
                                        },
                                    )
                                }
                            }
                        }

                        Column {
                            Text(
                                text = stringResource(R.string.app_name),
                                style = MaterialTheme.typography.headlineMedium,
                                color = Color.White,
                            )
                            Text(
                                text = stringResource(R.string.app_subtitle_hi),
                                style = MaterialTheme.typography.titleMedium.copy(
                                    fontFamily = DevanagariFontFamily,
                                ),
                                color = Color(0xFFFFE5B4),
                            )
                            Spacer(modifier = Modifier.height(4.dp))
                            Text(
                                text = "Official PDF Manuals, Circulars & Amendments • Bilingual (EN / हिन्दी)",
                                style = MaterialTheme.typography.bodySmall,
                                color = Color.White.copy(alpha = 0.85f),
                            )
                        }
                    }
                }

                // Quick Navigation & Sync Bar
                FlowRow(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    OutlinedButton(
                        onClick = { viewModel.syncTaxonomy() },
                        enabled = !state.isSyncing,
                        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp),
                        modifier = Modifier.testTag("sync_taxonomy_button"),
                    ) {
                        if (state.isSyncing) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(16.dp),
                                strokeWidth = 2.dp,
                            )
                        } else {
                            Icon(
                                imageVector = Icons.Filled.Sync,
                                contentDescription = null,
                                modifier = Modifier.size(16.dp),
                            )
                        }
                        Spacer(modifier = Modifier.width(6.dp))
                        Text("Sync Catalog", style = MaterialTheme.typography.labelMedium)
                    }

                    OutlinedButton(
                        onClick = onOpenAccount,
                        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp),
                        modifier = Modifier.testTag("open_account_button"),
                    ) {
                        Icon(
                            imageVector = Icons.Filled.Person,
                            contentDescription = null,
                            modifier = Modifier.size(16.dp),
                        )
                        Spacer(modifier = Modifier.width(6.dp))
                        Text(
                            text = state.userProfile?.fullName ?: state.userProfile?.email ?: "Sign In",
                            style = MaterialTheme.typography.labelMedium,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }

                    OutlinedButton(
                        onClick = onOpenAdmin,
                        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp),
                        modifier = Modifier.testTag("open_admin_button"),
                    ) {
                        Icon(
                            imageVector = Icons.Filled.AdminPanelSettings,
                            contentDescription = null,
                            modifier = Modifier.size(16.dp),
                        )
                        Spacer(modifier = Modifier.width(6.dp))
                        Text(
                            text = if (state.userProfile?.role == UserRole.ADMIN) {
                                "Admin Console"
                            } else {
                                "Admin"
                            },
                            style = MaterialTheme.typography.labelMedium,
                        )
                    }

                    TextButton(
                        onClick = { showHierarchySheet = true },
                        modifier = Modifier.testTag("search_hierarchy_button"),
                    ) {
                        Icon(
                            imageVector = Icons.Filled.Layers,
                            contentDescription = null,
                            modifier = Modifier.size(16.dp),
                        )
                        Spacer(modifier = Modifier.width(4.dp))
                        Text("Search Rules", style = MaterialTheme.typography.labelMedium)
                    }
                }

                AnimatedVisibility(visible = state.syncMessage != null) {
                    state.syncMessage?.let { msg ->
                        Surface(
                            shape = MaterialTheme.shapes.small,
                            color = MaterialTheme.colorScheme.surfaceVariant,
                            border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
                        ) {
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(horizontal = 12.dp, vertical = 8.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.SpaceBetween,
                            ) {
                                Text(
                                    text = msg,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                    modifier = Modifier.weight(1f),
                                )
                                TextButton(onClick = { viewModel.dismissSyncMessage() }) {
                                    Text("Dismiss")
                                }
                            }
                        }
                    }
                }

                // 1. Railway Zone Selector
                SectionCard(
                    stepNumber = "1",
                    title = stringResource(R.string.label_zone),
                    subtitle = "Western Railway active initially; database-ready for all 17 Zones",
                ) {
                    ExposedDropdownMenuBox(
                        expanded = zoneMenuExpanded,
                        onExpandedChange = { zoneMenuExpanded = !zoneMenuExpanded },
                    ) {
                        OutlinedTextField(
                            value = state.selectedZone?.let { "${it.name} (${it.code})" } ?: "",
                            onValueChange = {},
                            readOnly = true,
                            leadingIcon = {
                                Icon(Icons.Filled.Train, contentDescription = null)
                            },
                            trailingIcon = {
                                Icon(Icons.Filled.ArrowDropDown, contentDescription = "Select zone")
                            },
                            label = { Text("Active Railway Zone") },
                            modifier = Modifier
                                .menuAnchor(MenuAnchorType.PrimaryNotEditable)
                                .fillMaxWidth()
                                .testTag("zone_selector"),
                        )
                        ExposedDropdownMenu(
                            expanded = zoneMenuExpanded,
                            onDismissRequest = { zoneMenuExpanded = false },
                        ) {
                            state.zones.forEach { zone ->
                                DropdownMenuItem(
                                    text = {
                                        Column {
                                            Text("${zone.name} (${zone.code})")
                                            zone.nameHi?.let {
                                                Text(
                                                    text = it,
                                                    style = MaterialTheme.typography.bodySmall.copy(
                                                        fontFamily = DevanagariFontFamily,
                                                    ),
                                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                                )
                                            }
                                        }
                                    },
                                    onClick = {
                                        viewModel.selectZone(zone)
                                        zoneMenuExpanded = false
                                    },
                                )
                            }
                        }
                    }
                }

                // 2. Division Selector
                SectionCard(
                    stepNumber = "2",
                    title = stringResource(R.string.label_division),
                    subtitle = "Select your operating division under ${state.selectedZone?.name ?: "Western Railway"}",
                ) {
                    FlowRow(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        state.divisions.forEach { division ->
                            val selected = state.selectedDivision?.id == division.id
                            SelectionPillCard(
                                title = division.name,
                                subtitle = division.nameHi ?: division.code,
                                code = division.code,
                                selected = selected,
                                onClick = { viewModel.selectDivision(division) },
                                modifier = Modifier.testTag("division_card_${division.code.lowercase()}"),
                            )
                        }
                    }
                }

                // 3. Department Selector
                SectionCard(
                    stepNumber = "3",
                    title = stringResource(R.string.label_department),
                    subtitle = "Prioritizes your department first, while honoring Railway Board legal authority",
                ) {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        state.departments.forEach { dept ->
                            val selected = state.selectedDepartment?.id == dept.id
                            DepartmentSelectionRow(
                                department = dept,
                                selected = selected,
                                icon = departmentIcon(dept.code),
                                onClick = { viewModel.selectDepartment(dept) },
                                modifier = Modifier.testTag("department_row_${dept.code.lowercase()}"),
                            )
                        }
                    }
                }

                Spacer(modifier = Modifier.height(12.dp))
            }
        }
    }
}

@Composable
private fun SectionCard(
    stepNumber: String,
    title: String,
    subtitle: String,
    content: @Composable () -> Unit,
) {
    Card(
        shape = MaterialTheme.shapes.large,
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Surface(
                    shape = RoundedCornerShape(10.dp),
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(28.dp),
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        Text(
                            text = stepNumber,
                            style = MaterialTheme.typography.labelLarge,
                            color = MaterialTheme.colorScheme.onPrimary,
                        )
                    }
                }
                Spacer(modifier = Modifier.width(10.dp))
                Column {
                    Text(
                        text = title,
                        style = MaterialTheme.typography.titleMedium,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    Text(
                        text = subtitle,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
            content()
        }
    }
}

@Composable
private fun SelectionPillCard(
    title: String,
    subtitle: String,
    code: String,
    selected: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        onClick = onClick,
        modifier = modifier,
        shape = MaterialTheme.shapes.medium,
        color = if (selected) {
            MaterialTheme.colorScheme.primaryContainer
        } else {
            MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.55f)
        },
        border = BorderStroke(
            width = if (selected) 1.5.dp else 1.dp,
            color = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outlineVariant,
        ),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 12.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column {
                Text(
                    text = title,
                    style = MaterialTheme.typography.labelLarge.copy(
                        fontWeight = if (selected) FontWeight.Bold else FontWeight.SemiBold,
                    ),
                    color = if (selected) {
                        MaterialTheme.colorScheme.onPrimaryContainer
                    } else {
                        MaterialTheme.colorScheme.onSurface
                    },
                )
                Text(
                    text = "$subtitle ($code)",
                    style = MaterialTheme.typography.labelSmall.copy(
                        fontFamily = DevanagariFontFamily,
                    ),
                    color = if (selected) {
                        MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.85f)
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                )
            }
            if (selected) {
                Spacer(modifier = Modifier.width(8.dp))
                Icon(
                    imageVector = Icons.Filled.Check,
                    contentDescription = "Selected",
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(18.dp),
                )
            }
        }
    }
}

@Composable
private fun DepartmentSelectionRow(
    department: RailwayDepartment,
    selected: Boolean,
    icon: ImageVector,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(
        onClick = onClick,
        modifier = modifier.fillMaxWidth(),
        shape = MaterialTheme.shapes.medium,
        color = if (selected) {
            MaterialTheme.colorScheme.primaryContainer
        } else {
            MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.4f)
        },
        border = BorderStroke(
            width = if (selected) 1.5.dp else 1.dp,
            color = if (selected) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.outlineVariant,
        ),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 12.dp, vertical = 12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.weight(1f),
            ) {
                Surface(
                    shape = RoundedCornerShape(10.dp),
                    color = if (selected) {
                        MaterialTheme.colorScheme.primary
                    } else {
                        MaterialTheme.colorScheme.surface
                    },
                    modifier = Modifier.size(36.dp),
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        Icon(
                            imageVector = icon,
                            contentDescription = null,
                            tint = if (selected) {
                                MaterialTheme.colorScheme.onPrimary
                            } else {
                                MaterialTheme.colorScheme.primary
                            },
                            modifier = Modifier.size(20.dp),
                        )
                    }
                }
                Spacer(modifier = Modifier.width(12.dp))
                Column {
                    Text(
                        text = department.name,
                        style = MaterialTheme.typography.titleSmall.copy(
                            fontWeight = if (selected) FontWeight.Bold else FontWeight.SemiBold,
                        ),
                        color = if (selected) {
                            MaterialTheme.colorScheme.onPrimaryContainer
                        } else {
                            MaterialTheme.colorScheme.onSurface
                        },
                    )
                    department.nameHi?.let { hindi ->
                        Text(
                            text = hindi,
                            style = MaterialTheme.typography.bodySmall.copy(
                                fontFamily = DevanagariFontFamily,
                            ),
                            color = if (selected) {
                                MaterialTheme.colorScheme.onPrimaryContainer.copy(alpha = 0.85f)
                            } else {
                                MaterialTheme.colorScheme.onSurfaceVariant
                            },
                        )
                    }
                }
            }
            if (selected) {
                Icon(
                    imageVector = Icons.Filled.Check,
                    contentDescription = "Selected",
                    tint = MaterialTheme.colorScheme.primary,
                )
            }
        }
    }
}

private fun departmentIcon(code: String): ImageVector = when (code.uppercase()) {
    "ENG" -> Icons.Filled.Construction
    "OPT" -> Icons.Filled.Train
    "COM" -> Icons.Filled.ReceiptLong
    "PER" -> Icons.Filled.Groups
    "ELE" -> Icons.Filled.ElectricBolt
    "MEC" -> Icons.Filled.Engineering
    "SNT" -> Icons.Filled.SettingsInputAntenna
    "ACC" -> Icons.Filled.AccountBalance
    "STR" -> Icons.Filled.Inventory2
    "MED" -> Icons.Filled.LocalHospital
    "SAF" -> Icons.Filled.HealthAndSafety
    "RPF" -> Icons.Filled.Security
    else -> Icons.Filled.Build
}
