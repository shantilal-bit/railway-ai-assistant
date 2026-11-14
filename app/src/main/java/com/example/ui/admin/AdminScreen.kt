package com.example.ui.admin

import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Block
import androidx.compose.material.icons.filled.CloudUpload
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material.icons.filled.Link
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material.icons.filled.Publish
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Replay
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MenuAnchorType
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.example.R
import com.example.domain.model.AdminDocumentItem
import com.example.domain.model.RailwayDepartment
import com.example.domain.model.RailwayDivision
import com.example.domain.model.RailwayZone
import com.example.domain.model.ScopeLevel
import com.example.ui.theme.RailSignalGreen
import com.example.ui.theme.RailSignalGreenContainer

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun AdminScreen(
    viewModel: AdminViewModel,
    onNavigateBack: () -> Unit,
    onOpenAccount: () -> Unit,
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val context = LocalContext.current

    var isDriveImportMode by remember { mutableStateOf(false) }
    var selectedPdfUri by remember { mutableStateOf<Uri?>(null) }
    var selectedPdfName by remember { mutableStateOf<String?>(null) }
    var driveUrl by remember { mutableStateOf("") }

    var title by remember { mutableStateOf("") }
    var documentNumber by remember { mutableStateOf("") }
    var docType by remember { mutableStateOf("CIRCULAR") }
    var issuingAuthority by remember { mutableStateOf("Western Railway HQ") }
    var authorityRankText by remember { mutableStateOf("70") }
    var scopeLevel by remember { mutableStateOf(ScopeLevel.DEPARTMENT) }

    var selectedDivision by remember(state.selectedZoneId) { mutableStateOf<RailwayDivision?>(null) }
    var selectedDepartment by remember { mutableStateOf<RailwayDepartment?>(null) }

    var issueDate by remember { mutableStateOf("") }
    var effectiveDate by remember { mutableStateOf("") }
    var supersedesDocId by remember { mutableStateOf("") }
    var requiresOcr by remember { mutableStateOf(false) }

    var docTypeExpanded by remember { mutableStateOf(false) }
    var scopeExpanded by remember { mutableStateOf(false) }
    var zoneExpanded by remember { mutableStateOf(false) }
    var divisionExpanded by remember { mutableStateOf(false) }
    var departmentExpanded by remember { mutableStateOf(false) }

    val selectedZone: RailwayZone? = remember(state.zones, state.selectedZoneId) {
        state.zones.firstOrNull { it.id == state.selectedZoneId } ?: state.zones.firstOrNull()
    }

    LaunchedEffect(state.divisions) {
        if (selectedDivision == null || state.divisions.none { it.id == selectedDivision?.id }) {
            selectedDivision = state.divisions.firstOrNull()
        }
    }
    LaunchedEffect(state.departments) {
        if (selectedDepartment == null || state.departments.none { it.id == selectedDepartment?.id }) {
            selectedDepartment = state.departments.firstOrNull()
        }
    }

    val docTypes = remember {
        listOf("CIRCULAR", "MANUAL", "RULE_BOOK", "JPO", "AMENDMENT_SLIP", "ACT", "GAZETTE", "OTHER")
    }

    // Play-policy compliant Storage Access Framework picker for PDFs
    val pdfPickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenDocument(),
    ) { uri ->
        if (uri != null) {
            selectedPdfUri = uri
            context.contentResolver.query(uri, null, null, null, null)?.use { cursor ->
                val idx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (cursor.moveToFirst() && idx >= 0) {
                    selectedPdfName = cursor.getString(idx)
                }
            }
            if (selectedPdfName.isNullOrBlank()) {
                selectedPdfName = "official_document.pdf"
            }
        }
    }

    LaunchedEffect(state.isAdmin) {
        if (state.isAdmin) {
            viewModel.refreshDocuments()
        }
    }

    Scaffold(
        contentWindowInsets = WindowInsets.safeDrawing,
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.primary,
                    titleContentColor = MaterialTheme.colorScheme.onPrimary,
                    navigationIconContentColor = MaterialTheme.colorScheme.onPrimary,
                    actionIconContentColor = MaterialTheme.colorScheme.onPrimary,
                ),
                navigationIcon = {
                    IconButton(onClick = onNavigateBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
                title = { Text(stringResource(R.string.admin_panel_title)) },
                actions = {
                    if (state.isAdmin) {
                        IconButton(onClick = { viewModel.refreshDocuments() }) {
                            Icon(Icons.Filled.Refresh, contentDescription = "Refresh documents")
                        }
                    }
                },
            )
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
                    .widthIn(max = 660.dp)
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                if (!state.isAdmin) {
                    Card(
                        shape = MaterialTheme.shapes.large,
                        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
                    ) {
                        Column(
                            modifier = Modifier.padding(18.dp),
                            verticalArrangement = Arrangement.spacedBy(10.dp),
                        ) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Icon(
                                    imageVector = Icons.Filled.Lock,
                                    contentDescription = null,
                                    tint = MaterialTheme.colorScheme.secondary,
                                )
                                Spacer(modifier = Modifier.width(8.dp))
                                Text(
                                    text = "Administrator Access Required",
                                    style = MaterialTheme.typography.titleMedium,
                                )
                            }
                            Text(
                                text = "Only authorized Railway Administrators can upload official PDFs, import public Google Drive links, re-run document indexing, link amendments, publish circulars, or disable outdated records.",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            Text(
                                text = "Current role: ${state.userProfile?.role?.apiValue ?: "not signed in"}",
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.primary,
                            )
                            Button(
                                onClick = onOpenAccount,
                                modifier = Modifier.testTag("admin_signin_button"),
                            ) {
                                Text("Sign In with Admin Account")
                            }
                        }
                    }
                } else {
                    // Authorized Admin Upload / Drive Import Form
                    Card(
                        shape = MaterialTheme.shapes.large,
                        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
                    ) {
                        Column(
                            modifier = Modifier.padding(16.dp),
                            verticalArrangement = Arrangement.spacedBy(10.dp),
                        ) {
                            Text(
                                text = "Ingest Official Railway PDF",
                                style = MaterialTheme.typography.titleMedium,
                            )

                            SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
                                SegmentedButton(
                                    selected = !isDriveImportMode,
                                    onClick = { isDriveImportMode = false },
                                    shape = SegmentedButtonDefaults.itemShape(index = 0, count = 2),
                                    modifier = Modifier.testTag("admin_upload_mode_file"),
                                ) {
                                    Text("Upload PDF")
                                }
                                SegmentedButton(
                                    selected = isDriveImportMode,
                                    onClick = { isDriveImportMode = true },
                                    shape = SegmentedButtonDefaults.itemShape(index = 1, count = 2),
                                    modifier = Modifier.testTag("admin_upload_mode_drive"),
                                ) {
                                    Text("Google Drive Link")
                                }
                            }

                            if (!isDriveImportMode) {
                                OutlinedButton(
                                    onClick = { pdfPickerLauncher.launch(arrayOf("application/pdf")) },
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .testTag("admin_pick_pdf_button"),
                                ) {
                                    Icon(Icons.Filled.PictureAsPdf, contentDescription = null)
                                    Spacer(modifier = Modifier.width(8.dp))
                                    Text(selectedPdfName ?: "Select PDF Document (Max 50 MB)")
                                }
                            } else {
                                OutlinedTextField(
                                    value = driveUrl,
                                    onValueChange = { driveUrl = it },
                                    label = { Text("Public Google Drive PDF Share Link") },
                                    placeholder = { Text("https://drive.google.com/file/d/.../view") },
                                    leadingIcon = { Icon(Icons.Filled.Link, contentDescription = null) },
                                    singleLine = true,
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .testTag("admin_drive_url_input"),
                                )
                            }

                            OutlinedTextField(
                                value = title,
                                onValueChange = { title = it },
                                label = { Text("Official Document Title") },
                                singleLine = true,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .testTag("admin_title_input"),
                            )
                            OutlinedTextField(
                                value = documentNumber,
                                onValueChange = { documentNumber = it },
                                label = { Text("Document / Circular / RBE Number") },
                                singleLine = true,
                                modifier = Modifier.fillMaxWidth(),
                            )

                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                ExposedDropdownMenuBox(
                                    expanded = docTypeExpanded,
                                    onExpandedChange = { docTypeExpanded = !docTypeExpanded },
                                    modifier = Modifier.weight(1f),
                                ) {
                                    OutlinedTextField(
                                        value = docType,
                                        onValueChange = {},
                                        readOnly = true,
                                        trailingIcon = { Icon(Icons.Filled.ArrowDropDown, contentDescription = null) },
                                        label = { Text("Document Type") },
                                        modifier = Modifier
                                            .menuAnchor(MenuAnchorType.PrimaryNotEditable)
                                            .fillMaxWidth(),
                                    )
                                    ExposedDropdownMenu(
                                        expanded = docTypeExpanded,
                                        onDismissRequest = { docTypeExpanded = false },
                                    ) {
                                        docTypes.forEach { t ->
                                            DropdownMenuItem(
                                                text = { Text(t) },
                                                onClick = {
                                                    docType = t
                                                    docTypeExpanded = false
                                                },
                                            )
                                        }
                                    }
                                }

                                OutlinedTextField(
                                    value = authorityRankText,
                                    onValueChange = { authorityRankText = it.filter { ch -> ch.isDigit() }.take(3) },
                                    label = { Text("Authority Rank (1–100)") },
                                    singleLine = true,
                                    modifier = Modifier.weight(0.8f),
                                )
                            }

                            OutlinedTextField(
                                value = issuingAuthority,
                                onValueChange = { issuingAuthority = it },
                                label = { Text("Issuing Authority (e.g. Railway Board, PCPO WR)") },
                                singleLine = true,
                                modifier = Modifier.fillMaxWidth(),
                            )

                            // Scope Level + Zone + Division + Department Selectors
                            ExposedDropdownMenuBox(
                                expanded = scopeExpanded,
                                onExpandedChange = { scopeExpanded = !scopeExpanded },
                            ) {
                                OutlinedTextField(
                                    value = scopeLevel.label,
                                    onValueChange = {},
                                    readOnly = true,
                                    trailingIcon = { Icon(Icons.Filled.ArrowDropDown, contentDescription = null) },
                                    label = { Text("Applicability Scope") },
                                    modifier = Modifier
                                        .menuAnchor(MenuAnchorType.PrimaryNotEditable)
                                        .fillMaxWidth(),
                                )
                                ExposedDropdownMenu(
                                    expanded = scopeExpanded,
                                    onDismissRequest = { scopeExpanded = false },
                                ) {
                                    ScopeLevel.entries.forEach { lvl ->
                                        DropdownMenuItem(
                                            text = { Text(lvl.label) },
                                            onClick = {
                                                scopeLevel = lvl
                                                authorityRankText = when (lvl) {
                                                    ScopeLevel.RAILWAY_BOARD -> "100"
                                                    ScopeLevel.COMMON -> "80"
                                                    ScopeLevel.ZONE -> "70"
                                                    ScopeLevel.DIVISION -> "60"
                                                    ScopeLevel.DEPARTMENT -> "50"
                                                }
                                                scopeExpanded = false
                                            },
                                        )
                                    }
                                }
                            }

                            if (scopeLevel in listOf(ScopeLevel.DEPARTMENT, ScopeLevel.DIVISION, ScopeLevel.ZONE)) {
                                ExposedDropdownMenuBox(
                                    expanded = zoneExpanded,
                                    onExpandedChange = { if (state.zones.isNotEmpty()) zoneExpanded = !zoneExpanded },
                                ) {
                                    OutlinedTextField(
                                        value = selectedZone?.let { "${it.name} (${it.code})" } ?: "",
                                        onValueChange = {},
                                        readOnly = true,
                                        trailingIcon = { Icon(Icons.Filled.ArrowDropDown, contentDescription = null) },
                                        label = { Text("Zone") },
                                        modifier = Modifier
                                            .menuAnchor(MenuAnchorType.PrimaryNotEditable)
                                            .fillMaxWidth(),
                                    )
                                    ExposedDropdownMenu(
                                        expanded = zoneExpanded,
                                        onDismissRequest = { zoneExpanded = false },
                                    ) {
                                        state.zones.forEach { z ->
                                            DropdownMenuItem(
                                                text = { Text("${z.name} (${z.code})") },
                                                onClick = {
                                                    viewModel.selectZone(z.id)
                                                    zoneExpanded = false
                                                },
                                            )
                                        }
                                    }
                                }
                            }

                            if (scopeLevel in listOf(ScopeLevel.DEPARTMENT, ScopeLevel.DIVISION)) {
                                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    ExposedDropdownMenuBox(
                                        expanded = divisionExpanded,
                                        onExpandedChange = {
                                            if (state.divisions.isNotEmpty()) divisionExpanded = !divisionExpanded
                                        },
                                        modifier = Modifier.weight(1f),
                                    ) {
                                        OutlinedTextField(
                                            value = selectedDivision?.let { "${it.name} (${it.code})" } ?: "All Divisions (Zone-wide Dept)",
                                            onValueChange = {},
                                            readOnly = true,
                                            trailingIcon = { Icon(Icons.Filled.ArrowDropDown, contentDescription = null) },
                                            label = { Text("Division") },
                                            modifier = Modifier
                                                .menuAnchor(MenuAnchorType.PrimaryNotEditable)
                                                .fillMaxWidth(),
                                        )
                                        ExposedDropdownMenu(
                                            expanded = divisionExpanded,
                                            onDismissRequest = { divisionExpanded = false },
                                        ) {
                                            DropdownMenuItem(
                                                text = { Text("All Divisions (Zone-wide Dept)") },
                                                onClick = {
                                                    selectedDivision = null
                                                    divisionExpanded = false
                                                },
                                            )
                                            state.divisions.forEach { d ->
                                                DropdownMenuItem(
                                                    text = { Text("${d.name} (${d.code})") },
                                                    onClick = {
                                                        selectedDivision = d
                                                        divisionExpanded = false
                                                    },
                                                )
                                            }
                                        }
                                    }

                                    if (scopeLevel == ScopeLevel.DEPARTMENT) {
                                        ExposedDropdownMenuBox(
                                            expanded = departmentExpanded,
                                            onExpandedChange = {
                                                if (state.departments.isNotEmpty()) departmentExpanded = !departmentExpanded
                                            },
                                            modifier = Modifier.weight(1f),
                                        ) {
                                            OutlinedTextField(
                                                value = selectedDepartment?.let { "${it.name} (${it.code})" } ?: "",
                                                onValueChange = {},
                                                readOnly = true,
                                                trailingIcon = { Icon(Icons.Filled.ArrowDropDown, contentDescription = null) },
                                                label = { Text("Department") },
                                                modifier = Modifier
                                                    .menuAnchor(MenuAnchorType.PrimaryNotEditable)
                                                    .fillMaxWidth(),
                                            )
                                            ExposedDropdownMenu(
                                                expanded = departmentExpanded,
                                                onDismissRequest = { departmentExpanded = false },
                                            ) {
                                                state.departments.forEach { dept ->
                                                    DropdownMenuItem(
                                                        text = { Text("${dept.name} (${dept.code})") },
                                                        onClick = {
                                                            selectedDepartment = dept
                                                            departmentExpanded = false
                                                        },
                                                    )
                                                }
                                            }
                                        }
                                    }
                                }
                            }

                            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                OutlinedTextField(
                                    value = issueDate,
                                    onValueChange = { issueDate = it },
                                    label = { Text("Issue Date (YYYY-MM-DD)") },
                                    singleLine = true,
                                    modifier = Modifier.weight(1f),
                                )
                                OutlinedTextField(
                                    value = effectiveDate,
                                    onValueChange = { effectiveDate = it },
                                    label = { Text("Effective Date (YYYY-MM-DD)") },
                                    singleLine = true,
                                    modifier = Modifier.weight(1f),
                                )
                            }

                            OutlinedTextField(
                                value = supersedesDocId,
                                onValueChange = { supersedesDocId = it },
                                label = { Text("Supersedes / Amends Doc ID (Optional)") },
                                singleLine = true,
                                modifier = Modifier.fillMaxWidth(),
                            )

                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                horizontalArrangement = Arrangement.SpaceBetween,
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    text = "Force Bilingual OCR (English + Hindi)",
                                    style = MaterialTheme.typography.bodyMedium,
                                )
                                Switch(checked = requiresOcr, onCheckedChange = { requiresOcr = it })
                            }

                            val rankInt = authorityRankText.toIntOrNull()?.coerceIn(1, 100)
                            val canSubmit = title.isNotBlank() &&
                                issuingAuthority.isNotBlank() &&
                                !state.isLoading &&
                                (if (isDriveImportMode) driveUrl.isNotBlank() else selectedPdfUri != null)

                            Button(
                                onClick = {
                                    if (isDriveImportMode) {
                                        viewModel.importGoogleDrivePdf(
                                            driveUrl = driveUrl,
                                            title = title,
                                            documentNumber = documentNumber,
                                            documentType = docType,
                                            issuingAuthority = issuingAuthority,
                                            authorityRank = rankInt,
                                            scopeLevel = scopeLevel,
                                            zone = selectedZone,
                                            division = selectedDivision,
                                            department = selectedDepartment,
                                            issueDate = issueDate,
                                            effectiveDate = effectiveDate,
                                            requiresOcr = requiresOcr,
                                            supersedesDocumentId = supersedesDocId,
                                        )
                                    } else {
                                        val uri = selectedPdfUri ?: return@Button
                                        viewModel.uploadAndRegisterPdf(
                                            contentResolver = context.contentResolver,
                                            pdfUri = uri,
                                            fileName = selectedPdfName ?: "document.pdf",
                                            title = title,
                                            documentNumber = documentNumber,
                                            documentType = docType,
                                            issuingAuthority = issuingAuthority,
                                            authorityRank = rankInt,
                                            scopeLevel = scopeLevel,
                                            zone = selectedZone,
                                            division = selectedDivision,
                                            department = selectedDepartment,
                                            issueDate = issueDate,
                                            effectiveDate = effectiveDate,
                                            requiresOcr = requiresOcr,
                                            supersedesDocumentId = supersedesDocId,
                                        )
                                    }
                                },
                                enabled = canSubmit,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .testTag("admin_submit_document_button"),
                            ) {
                                if (state.isLoading) {
                                    CircularProgressIndicator(
                                        modifier = Modifier.size(18.dp),
                                        strokeWidth = 2.dp,
                                        color = MaterialTheme.colorScheme.onPrimary,
                                    )
                                } else {
                                    Icon(
                                        imageVector = if (isDriveImportMode) Icons.Filled.Link else Icons.Filled.CloudUpload,
                                        contentDescription = null,
                                    )
                                }
                                Spacer(modifier = Modifier.width(8.dp))
                                Text(
                                    if (isDriveImportMode) {
                                        "Import Drive PDF & Index"
                                    } else {
                                        "Upload, Register & Index PDF"
                                    },
                                )
                            }
                        }
                    }

                    state.statusMessage?.let { msg ->
                        Surface(
                            shape = MaterialTheme.shapes.small,
                            color = if (state.isError) {
                                MaterialTheme.colorScheme.secondaryContainer
                            } else {
                                MaterialTheme.colorScheme.primaryContainer
                            },
                        ) {
                            Text(
                                text = msg,
                                style = MaterialTheme.typography.bodySmall,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(12.dp),
                            )
                        }
                    }

                    // Document Registry + Search
                    Text(
                        text = "Document Registry (${state.documents.size})",
                        style = MaterialTheme.typography.titleMedium,
                    )

                    OutlinedTextField(
                        value = state.searchQuery,
                        onValueChange = viewModel::onSearchQueryChanged,
                        label = { Text("Search documents by title, RBE/circular no., or authority") },
                        leadingIcon = { Icon(Icons.Filled.Search, contentDescription = null) },
                        singleLine = true,
                        modifier = Modifier
                            .fillMaxWidth()
                            .testTag("admin_search_input"),
                    )

                    state.documents.forEach { doc ->
                        AdminDocumentCard(
                            doc = doc,
                            onPublish = { viewModel.updateStatus(doc.id, "published") },
                            onDisable = { viewModel.updateStatus(doc.id, "disabled", "Outdated record") },
                            onRetryIngestion = { viewModel.reprocessDocument(doc.id, forceOcr = doc.requiresOcr) },
                        )
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun AdminDocumentCard(
    doc: AdminDocumentItem,
    onPublish: () -> Unit,
    onDisable: () -> Unit,
    onRetryIngestion: () -> Unit,
) {
    val ingestionColor = when (doc.ingestionStatus.lowercase()) {
        "completed" -> RailSignalGreenContainer
        "failed" -> MaterialTheme.colorScheme.errorContainer
        else -> MaterialTheme.colorScheme.secondaryContainer
    }
    val ingestionTextColor = when (doc.ingestionStatus.lowercase()) {
        "completed" -> RailSignalGreen
        "failed" -> MaterialTheme.colorScheme.onErrorContainer
        else -> MaterialTheme.colorScheme.onSecondaryContainer
    }

    Card(
        shape = MaterialTheme.shapes.medium,
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Top,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = doc.title,
                        style = MaterialTheme.typography.titleSmall.copy(fontWeight = FontWeight.SemiBold),
                    )
                    val numberAndAuth = listOfNotNull(
                        doc.documentNumber?.takeIf { it.isNotBlank() },
                        doc.issuingAuthority,
                    ).joinToString(" • ")
                    if (numberAndAuth.isNotBlank()) {
                        Text(
                            text = numberAndAuth,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                Spacer(modifier = Modifier.width(8.dp))
                Surface(
                    shape = RoundedCornerShape(999.dp),
                    color = ingestionColor,
                ) {
                    Text(
                        text = "Index: ${doc.ingestionStatus.uppercase()}",
                        style = MaterialTheme.typography.labelSmall,
                        color = ingestionTextColor,
                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
                    )
                }
            }

            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(10.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                Text(
                    text = "Type: ${doc.documentType}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = "Status: ${doc.status}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.primary,
                )
                Text(
                    text = "Authority Rank: ${doc.authorityRank}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = "Pages: ${doc.pageCount ?: 0} • Chunks: ${doc.chunkCount}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = "OCR: ${doc.ocrStatus}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                doc.effectiveDate?.let {
                    Text(
                        text = "Effective: $it",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            if (!doc.ingestionError.isNullOrBlank()) {
                Surface(
                    shape = MaterialTheme.shapes.small,
                    color = MaterialTheme.colorScheme.errorContainer,
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(8.dp),
                        verticalAlignment = Alignment.Top,
                    ) {
                        Icon(
                            imageVector = Icons.Filled.ErrorOutline,
                            contentDescription = "Ingestion error",
                            tint = MaterialTheme.colorScheme.onErrorContainer,
                            modifier = Modifier.size(16.dp),
                        )
                        Spacer(modifier = Modifier.width(6.dp))
                        Text(
                            text = doc.ingestionError,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onErrorContainer,
                        )
                    }
                }
            }

            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                OutlinedButton(
                    onClick = onRetryIngestion,
                    modifier = Modifier.testTag("admin_retry_button_${doc.id}"),
                ) {
                    Icon(Icons.Filled.Replay, contentDescription = null, modifier = Modifier.size(16.dp))
                    Spacer(modifier = Modifier.width(4.dp))
                    Text(if (doc.ingestionStatus == "failed") "Retry Ingestion" else "Re-Index")
                }

                OutlinedButton(
                    onClick = onPublish,
                    enabled = doc.status != "published" && doc.ingestionStatus == "completed",
                ) {
                    Icon(Icons.Filled.Publish, contentDescription = null, modifier = Modifier.size(16.dp))
                    Spacer(modifier = Modifier.width(4.dp))
                    Text("Publish")
                }

                OutlinedButton(
                    onClick = onDisable,
                    enabled = doc.status != "disabled",
                ) {
                    Icon(Icons.Filled.Block, contentDescription = null, modifier = Modifier.size(16.dp))
                    Spacer(modifier = Modifier.width(4.dp))
                    Text("Disable")
                }
            }
        }
    }
}
