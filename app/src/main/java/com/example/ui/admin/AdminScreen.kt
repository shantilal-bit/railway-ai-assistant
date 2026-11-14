package com.example.ui.admin

import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
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
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Block
import androidx.compose.material.icons.filled.CloudUpload
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material.icons.filled.Publish
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
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
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.example.R

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AdminScreen(
    viewModel: AdminViewModel,
    onNavigateBack: () -> Unit,
    onOpenAccount: () -> Unit,
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val context = LocalContext.current

    var selectedPdfUri by remember { mutableStateOf<Uri?>(null) }
    var selectedPdfName by remember { mutableStateOf<String?>(null) }
    var title by remember { mutableStateOf("") }
    var documentNumber by remember { mutableStateOf("") }
    var docType by remember { mutableStateOf("CIRCULAR") }
    var issuingAuthority by remember { mutableStateOf("Western Railway HQ") }
    var issueDate by remember { mutableStateOf("") }
    var effectiveDate by remember { mutableStateOf("") }
    var supersedesDocId by remember { mutableStateOf("") }
    var requiresOcr by remember { mutableStateOf(false) }
    var docTypeExpanded by remember { mutableStateOf(false) }

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
                    .widthIn(max = 640.dp)
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
                                text = "Only authorized Railway Administrators can upload official PDFs, enable document scanning, add amendment relationships, publish circulars, or disable outdated records.",
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
                    // Authorized Admin Upload Form
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
                                text = "Upload Official Railway PDF",
                                style = MaterialTheme.typography.titleMedium,
                            )
                            OutlinedButton(
                                onClick = { pdfPickerLauncher.launch(arrayOf("application/pdf")) },
                                modifier = Modifier.fillMaxWidth(),
                            ) {
                                Icon(Icons.Filled.PictureAsPdf, contentDescription = null)
                                Spacer(modifier = Modifier.width(8.dp))
                                Text(selectedPdfName ?: "Select PDF Document")
                            }

                            OutlinedTextField(
                                value = title,
                                onValueChange = { title = it },
                                label = { Text("Official Document Name") },
                                singleLine = true,
                                modifier = Modifier.fillMaxWidth(),
                            )
                            OutlinedTextField(
                                value = documentNumber,
                                onValueChange = { documentNumber = it },
                                label = { Text("Circular / RBE Number") },
                                singleLine = true,
                                modifier = Modifier.fillMaxWidth(),
                            )

                            ExposedDropdownMenuBox(
                                expanded = docTypeExpanded,
                                onExpandedChange = { docTypeExpanded = !docTypeExpanded },
                            ) {
                                OutlinedTextField(
                                    value = docType,
                                    onValueChange = {},
                                    readOnly = true,
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
                                value = issuingAuthority,
                                onValueChange = { issuingAuthority = it },
                                label = { Text("Issuing Authority") },
                                singleLine = true,
                                modifier = Modifier.fillMaxWidth(),
                            )

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
                                    label = { Text("Effective Date") },
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
                                    text = "Scanned PDF (Run OCR Pipeline)",
                                    style = MaterialTheme.typography.bodyMedium,
                                )
                                Switch(checked = requiresOcr, onCheckedChange = { requiresOcr = it })
                            }

                            Button(
                                onClick = {
                                    val uri = selectedPdfUri ?: return@Button
                                    val zone = state.zones.firstOrNull() ?: return@Button
                                    viewModel.uploadAndRegisterPdf(
                                        contentResolver = context.contentResolver,
                                        pdfUri = uri,
                                        fileName = selectedPdfName ?: "document.pdf",
                                        title = title,
                                        documentNumber = documentNumber,
                                        documentType = docType,
                                        issuingAuthority = issuingAuthority,
                                        zone = zone,
                                        division = state.divisions.firstOrNull(),
                                        department = state.departments.firstOrNull(),
                                        issueDate = issueDate,
                                        effectiveDate = effectiveDate,
                                        requiresOcr = requiresOcr,
                                        supersedesDocumentId = supersedesDocId,
                                    )
                                },
                                enabled = selectedPdfUri != null && title.isNotBlank() && !state.isLoading,
                                modifier = Modifier.fillMaxWidth(),
                            ) {
                                Icon(Icons.Filled.CloudUpload, contentDescription = null)
                                Spacer(modifier = Modifier.width(8.dp))
                                Text("Upload & Register PDF")
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

                    // Document Registry List
                    Text(
                        text = "Document Registry (${state.documents.size})",
                        style = MaterialTheme.typography.titleMedium,
                    )
                    state.documents.forEach { doc ->
                        Card(
                            shape = MaterialTheme.shapes.medium,
                            colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                            border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
                        ) {
                            Column(
                                modifier = Modifier.padding(12.dp),
                                verticalArrangement = Arrangement.spacedBy(6.dp),
                            ) {
                                Text(doc.title, style = MaterialTheme.typography.titleSmall)
                                Text(
                                    text = "${doc.documentType} • Status: ${doc.status} • OCR: ${doc.ocrStatus}",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                                )
                                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    OutlinedButton(
                                        onClick = { viewModel.updateStatus(doc.id, "published") },
                                        enabled = doc.status != "published",
                                    ) {
                                        Icon(Icons.Filled.Publish, contentDescription = null, modifier = Modifier.size(16.dp))
                                        Spacer(modifier = Modifier.width(4.dp))
                                        Text("Publish")
                                    }
                                    OutlinedButton(
                                        onClick = { viewModel.updateStatus(doc.id, "disabled", "Outdated record") },
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
                }
            }
        }
    }
}
