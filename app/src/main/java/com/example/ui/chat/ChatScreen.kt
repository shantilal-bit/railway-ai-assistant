package com.example.ui.chat

import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.BorderStroke
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
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.filled.AddComment
import androidx.compose.material.icons.filled.AttachFile
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.CloudOff
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.Dns
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Layers
import androidx.compose.material.icons.filled.MenuBook
import androidx.compose.material.icons.filled.PictureAsPdf
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.InputChip
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.example.R
import com.example.domain.model.AiEngineMode
import com.example.domain.model.ChatMessage
import com.example.domain.model.ChatSession
import com.example.domain.model.MessageSender
import com.example.domain.model.QueryLanguage
import com.example.ui.components.SearchHierarchySheet
import com.example.ui.components.ServerConnectionDialog
import com.example.ui.components.StructuredAnswerCard
import com.example.ui.theme.DevanagariFontFamily
import com.example.ui.theme.fontFamilyForText
import kotlinx.coroutines.launch
import java.text.DateFormat
import java.util.Date

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun ChatScreen(
    viewModel: ChatViewModel,
    onNavigateBack: () -> Unit,
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val snackbarHostState = remember { SnackbarHostState() }
    val clipboardManager = LocalClipboardManager.current
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val listState = rememberLazyListState()

    var showHistorySheet by remember { mutableStateOf(false) }
    var showHierarchySheet by remember { mutableStateOf(false) }
    var showServerDialog by remember { mutableStateOf(false) }

    val copiedText = stringResource(R.string.copied_to_clipboard)

    val pdfPickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.OpenDocument(),
    ) { uri ->
        if (uri != null) {
            var displayName = "official_rule.pdf"
            context.contentResolver.query(uri, null, null, null, null)?.use { cursor ->
                val idx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (cursor.moveToFirst() && idx >= 0) {
                    displayName = cursor.getString(idx) ?: displayName
                }
            }
            viewModel.attachPdf(uri, displayName)
        }
    }

    LaunchedEffect(state.messages.size) {
        if (state.messages.isNotEmpty()) {
            listState.animateScrollToItem(state.messages.size - 1)
        }
    }

    if (showHierarchySheet) {
        SearchHierarchySheet(onDismiss = { showHierarchySheet = false })
    }

    if (showServerDialog) {
        ServerConnectionDialog(
            currentBaseUrl = state.backendBaseUrl,
            health = state.backendHealth,
            onSaveAndTest = { viewModel.updateBackendBaseUrl(it) },
            onDismiss = { showServerDialog = false },
        )
    }

    if (showHistorySheet) {
        ChatHistorySheet(
            sessions = state.sessions,
            activeSessionId = state.activeSession?.id,
            onSelectSession = {
                viewModel.selectSession(it)
                showHistorySheet = false
            },
            onDeleteSession = { viewModel.deleteSession(it.id) },
            onNewChat = {
                viewModel.startNewChat()
                showHistorySheet = false
            },
            onDismiss = { showHistorySheet = false },
        )
    }

    Scaffold(
        contentWindowInsets = WindowInsets.safeDrawing,
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = MaterialTheme.colorScheme.primary,
                    titleContentColor = MaterialTheme.colorScheme.onPrimary,
                    navigationIconContentColor = MaterialTheme.colorScheme.onPrimary,
                    actionIconContentColor = MaterialTheme.colorScheme.onPrimary,
                ),
                navigationIcon = {
                    IconButton(
                        onClick = onNavigateBack,
                        modifier = Modifier.testTag("chat_back_button"),
                    ) {
                        Icon(
                            imageVector = Icons.AutoMirrored.Filled.ArrowBack,
                            contentDescription = "Change Zone, Division, or Department",
                        )
                    }
                },
                title = {
                    Column {
                        Text(
                            text = stringResource(R.string.app_name),
                            style = MaterialTheme.typography.titleMedium,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                        val scopeLabel = state.activeSession?.let {
                            "${it.zoneName} • ${it.divisionName} • ${it.departmentName}"
                        } ?: "Western Railway"
                        Text(
                            text = scopeLabel,
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onPrimary.copy(alpha = 0.85f),
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                },
                actions = {
                    IconButton(
                        onClick = { viewModel.startNewChat() },
                        modifier = Modifier.testTag("new_chat_button"),
                    ) {
                        Icon(
                            imageVector = Icons.Filled.AddComment,
                            contentDescription = stringResource(R.string.new_chat),
                        )
                    }
                    IconButton(
                        onClick = { showHistorySheet = true },
                        modifier = Modifier.testTag("chat_history_button"),
                    ) {
                        Icon(
                            imageVector = Icons.Filled.History,
                            contentDescription = stringResource(R.string.chat_history),
                        )
                    }
                    IconButton(
                        onClick = { showServerDialog = true },
                        modifier = Modifier.testTag("chat_server_button"),
                    ) {
                        Icon(
                            imageVector = Icons.Filled.Settings,
                            contentDescription = stringResource(R.string.server_settings_title),
                        )
                    }
                },
            )
        },
        bottomBar = {
            Surface(
                tonalElevation = 4.dp,
                shadowElevation = 6.dp,
                color = MaterialTheme.colorScheme.surface,
            ) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .navigationBarsPadding()
                        .imePadding(),
                    contentAlignment = Alignment.Center,
                ) {
                    Column(
                        modifier = Modifier
                            .widthIn(max = 680.dp)
                            .fillMaxWidth()
                            .padding(horizontal = 12.dp, vertical = 10.dp),
                    ) {
                        AnimatedVisibility(visible = state.isGenerating) {
                            Column(modifier = Modifier.padding(bottom = 8.dp)) {
                                LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
                                Spacer(modifier = Modifier.height(4.dp))
                                Text(
                                    text = if (state.engineMode == AiEngineMode.GEMINI_FIREBASE) {
                                        "Analyzing with Gemini 3.8 Flash via Firebase AI Logic…"
                                    } else {
                                        "Searching official PDFs across 5 tiers & verifying amendments…"
                                    },
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.primary,
                                )
                            }
                        }

                        if (state.engineMode == AiEngineMode.GEMINI_FIREBASE && state.attachedPdfName != null) {
                            InputChip(
                                selected = true,
                                onClick = { viewModel.clearAttachedPdf() },
                                label = {
                                    Text(
                                        text = "PDF: ${state.attachedPdfName}",
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                },
                                leadingIcon = {
                                    Icon(
                                        imageVector = Icons.Filled.PictureAsPdf,
                                        contentDescription = null,
                                        modifier = Modifier.size(16.dp),
                                    )
                                },
                                trailingIcon = {
                                    Icon(
                                        imageVector = Icons.Filled.Close,
                                        contentDescription = "Remove attached PDF",
                                        modifier = Modifier.size(16.dp),
                                    )
                                },
                                modifier = Modifier.padding(bottom = 6.dp),
                            )
                        }

                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.Bottom,
                        ) {
                            if (state.engineMode == AiEngineMode.GEMINI_FIREBASE) {
                                IconButton(
                                    onClick = { pdfPickerLauncher.launch(arrayOf("application/pdf")) },
                                    modifier = Modifier
                                        .size(48.dp)
                                        .testTag("attach_pdf_button"),
                                ) {
                                    Icon(
                                        imageVector = Icons.Filled.AttachFile,
                                        contentDescription = "Attach official Railway PDF for Gemini analysis",
                                        tint = MaterialTheme.colorScheme.primary,
                                    )
                                }
                            }

                            OutlinedTextField(
                                value = state.draftInput,
                                onValueChange = viewModel::onDraftChanged,
                                placeholder = {
                                    Text(
                                        text = stringResource(R.string.ask_placeholder),
                                        style = MaterialTheme.typography.bodyMedium,
                                    )
                                },
                                maxLines = 4,
                                modifier = Modifier
                                    .weight(1f)
                                    .testTag("chat_question_input"),
                                textStyle = MaterialTheme.typography.bodyMedium.copy(
                                    fontFamily = fontFamilyForText(state.draftInput),
                                ),
                            )
                            Spacer(modifier = Modifier.width(8.dp))
                            Surface(
                                onClick = { viewModel.sendQuestion(context.contentResolver) },
                                enabled = state.draftInput.isNotBlank() && !state.isGenerating,
                                shape = RoundedCornerShape(14.dp),
                                color = if (state.draftInput.isNotBlank() && !state.isGenerating) {
                                    MaterialTheme.colorScheme.primary
                                } else {
                                    MaterialTheme.colorScheme.surfaceVariant
                                },
                                modifier = Modifier
                                    .size(52.dp)
                                    .testTag("send_question_button"),
                            ) {
                                Box(contentAlignment = Alignment.Center) {
                                    if (state.isGenerating) {
                                        CircularProgressIndicator(
                                            modifier = Modifier.size(20.dp),
                                            strokeWidth = 2.dp,
                                        )
                                    } else {
                                        Icon(
                                            imageVector = Icons.AutoMirrored.Filled.Send,
                                            contentDescription = stringResource(R.string.send_question),
                                            tint = if (state.draftInput.isNotBlank()) {
                                                MaterialTheme.colorScheme.onPrimary
                                            } else {
                                                MaterialTheme.colorScheme.onSurfaceVariant
                                            },
                                        )
                                    }
                                }
                            }
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
                    .widthIn(max = 680.dp)
                    .fillMaxSize(),
            ) {
                // AI Engine + Language selector + Hierarchy info strip
                Surface(
                    color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.55f),
                    border = BorderStroke(0.5.dp, MaterialTheme.colorScheme.outlineVariant),
                ) {
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 12.dp, vertical = 6.dp),
                        verticalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            FlowRow(
                                horizontalArrangement = Arrangement.spacedBy(6.dp),
                                modifier = Modifier.weight(1f),
                            ) {
                                AiEngineMode.entries.forEach { mode ->
                                    FilterChip(
                                        selected = state.engineMode == mode,
                                        onClick = { viewModel.setEngineMode(mode) },
                                        leadingIcon = {
                                            Icon(
                                                imageVector = if (mode == AiEngineMode.GEMINI_FIREBASE) {
                                                    Icons.Filled.AutoAwesome
                                                } else {
                                                    Icons.Filled.Dns
                                                },
                                                contentDescription = null,
                                                modifier = Modifier.size(15.dp),
                                            )
                                        },
                                        label = {
                                            Text(
                                                text = mode.label,
                                                style = MaterialTheme.typography.labelSmall,
                                            )
                                        },
                                        modifier = Modifier.testTag("engine_chip_${mode.name.lowercase()}"),
                                    )
                                }
                            }

                            IconButton(
                                onClick = { showHierarchySheet = true },
                                modifier = Modifier.testTag("chat_hierarchy_button"),
                            ) {
                                Icon(
                                    imageVector = Icons.Filled.Layers,
                                    contentDescription = stringResource(R.string.search_hierarchy_title),
                                    tint = MaterialTheme.colorScheme.primary,
                                )
                            }
                        }

                        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            QueryLanguage.entries.forEach { lang ->
                                FilterChip(
                                    selected = state.queryLanguage == lang,
                                    onClick = { viewModel.setQueryLanguage(lang) },
                                    label = {
                                        Text(
                                            text = lang.label,
                                            style = MaterialTheme.typography.labelSmall.copy(
                                                fontFamily = fontFamilyForText(lang.label),
                                            ),
                                        )
                                    },
                                    modifier = Modifier.testTag("lang_chip_${lang.code}"),
                                )
                            }
                        }

                        if (state.engineMode == AiEngineMode.BACKEND_RAG && state.backendHealth?.isConnected == false) {
                            Surface(
                                shape = MaterialTheme.shapes.small,
                                color = MaterialTheme.colorScheme.tertiaryContainer,
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(bottom = 4.dp)
                                    .clickable { showServerDialog = true },
                            ) {
                                Row(
                                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Icon(
                                        imageVector = Icons.Filled.CloudOff,
                                        contentDescription = null,
                                        tint = MaterialTheme.colorScheme.onTertiaryContainer,
                                        modifier = Modifier.size(16.dp),
                                    )
                                    Spacer(modifier = Modifier.width(8.dp))
                                    Text(
                                        text = "Backend RAG offline (${state.backendBaseUrl}). Tap to configure, or use Gemini AI (Firebase).",
                                        style = MaterialTheme.typography.labelSmall,
                                        color = MaterialTheme.colorScheme.onTertiaryContainer,
                                    )
                                }
                            }
                        }
                    }
                }

                // Messages or Empty State
                if (state.messages.isEmpty()) {
                    ChatEmptyState(
                        divisionName = state.activeSession?.divisionName ?: "Western Railway",
                        departmentName = state.activeSession?.departmentName ?: "Department",
                        engineMode = state.engineMode,
                        onSelectQuestion = { viewModel.setPromptSuggestion(it) },
                        modifier = Modifier
                            .weight(1f)
                            .fillMaxWidth(),
                    )
                } else {
                    LazyColumn(
                        state = listState,
                        modifier = Modifier
                            .weight(1f)
                            .fillMaxWidth()
                            .testTag("chat_messages_list"),
                        contentPadding = PaddingValues(14.dp),
                        verticalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        items(state.messages, key = { it.id }) { msg ->
                            ChatMessageRow(
                                message = msg,
                                onCopyAnswer = { formatted ->
                                    clipboardManager.setText(AnnotatedString(formatted))
                                    scope.launch { snackbarHostState.showSnackbar(copiedText) }
                                },
                                onOpenServerSettings = { showServerDialog = true },
                            )
                        }
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ChatEmptyState(
    divisionName: String,
    departmentName: String,
    engineMode: AiEngineMode,
    onSelectQuestion: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    val starterQuestions = remember(divisionName, departmentName) {
        listOf(
            "Explain the 7-part structure and what I should verify in an official Railway Board leave rule circular.",
            "Summarize the attached Railway PDF circular and list the rule number, effective date, and page numbers.",
            "रेलवे कर्मचारियों के लिए चिकित्सा परीक्षण (Medical Category) और अवकाश नियमों की मुख्य बातें क्या हैं?",
            "DAR (Discipline & Appeal Rules) के तहत मेजर पेनल्टी चार्जशीट (SF-5) की प्रक्रिया समझाइए।",
        )
    }

    LazyColumn(
        modifier = modifier,
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        item {
            Card(
                shape = MaterialTheme.shapes.large,
                colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
            ) {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(
                            imageVector = Icons.Filled.MenuBook,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.primary,
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = "Official Railway Rules Search ($divisionName • $departmentName)",
                            style = MaterialTheme.typography.titleSmall,
                            color = MaterialTheme.colorScheme.onSurface,
                        )
                    }
                    Text(
                        text = if (engineMode == AiEngineMode.GEMINI_FIREBASE) {
                            "Gemini AI (Firebase) is active. Ask questions in English or हिन्दी, and optionally tap the paperclip button below to attach an official Railway PDF (up to 18 MB) so Gemini can cite exact rule numbers and PDF page numbers."
                        } else {
                            "Backend RAG mode is active. Questions search your Supabase pgvector database across the 5-tier hierarchy and Cloudflare R2 manuals."
                        },
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        text = "Every answer follows the 7-part verified format: Direct Answer, Detailed Explanation, Applicable Rule Number, Official Document Name, PDF Page Number, Amendment/Circular Reference, and Effective Date.",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.primary,
                    )
                }
            }
        }

        item {
            Text(
                text = "Tap a bilingual question to load into the box:",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }

        item {
            FlowRow(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                starterQuestions.forEachIndexed { idx, prompt ->
                    Surface(
                        onClick = { onSelectQuestion(prompt) },
                        shape = MaterialTheme.shapes.medium,
                        color = MaterialTheme.colorScheme.surface,
                        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
                        modifier = Modifier.testTag("starter_question_$idx"),
                    ) {
                        Text(
                            text = prompt,
                            style = MaterialTheme.typography.bodySmall.copy(
                                fontFamily = fontFamilyForText(prompt),
                            ),
                            color = MaterialTheme.colorScheme.onSurface,
                            modifier = Modifier.padding(12.dp),
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun ChatMessageRow(
    message: ChatMessage,
    onCopyAnswer: (String) -> Unit,
    onOpenServerSettings: () -> Unit,
) {
    when (message.sender) {
        MessageSender.USER -> {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End,
            ) {
                Surface(
                    shape = RoundedCornerShape(18.dp, 18.dp, 4.dp, 18.dp),
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.widthIn(max = 520.dp),
                ) {
                    Text(
                        text = message.text,
                        style = MaterialTheme.typography.bodyMedium.copy(
                            fontFamily = fontFamilyForText(message.text),
                        ),
                        color = MaterialTheme.colorScheme.onPrimary,
                        modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp),
                    )
                }
            }
        }

        MessageSender.ASSISTANT -> {
            val structured = message.structuredAnswer
            if (structured != null) {
                StructuredAnswerCard(
                    answer = structured,
                    onCopyAnswer = onCopyAnswer,
                )
            } else {
                Surface(
                    shape = MaterialTheme.shapes.large,
                    color = MaterialTheme.colorScheme.surface,
                    border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
                ) {
                    Text(
                        text = message.text,
                        style = MaterialTheme.typography.bodyMedium.copy(
                            fontFamily = fontFamilyForText(message.text),
                        ),
                        modifier = Modifier.padding(14.dp),
                    )
                }
            }
        }

        MessageSender.SYSTEM_ERROR -> {
            Surface(
                shape = MaterialTheme.shapes.medium,
                color = MaterialTheme.colorScheme.secondaryContainer,
                border = BorderStroke(1.dp, MaterialTheme.colorScheme.secondary.copy(alpha = 0.4f)),
            ) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(
                            imageVector = Icons.Filled.ErrorOutline,
                            contentDescription = null,
                            tint = MaterialTheme.colorScheme.secondary,
                            modifier = Modifier.size(18.dp),
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = "AI / Connection Error Notice",
                            style = MaterialTheme.typography.labelLarge,
                            color = MaterialTheme.colorScheme.onSecondaryContainer,
                        )
                    }
                    Spacer(modifier = Modifier.height(6.dp))
                    Text(
                        text = message.text,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSecondaryContainer,
                    )
                    Spacer(modifier = Modifier.height(8.dp))
                    OutlinedButton(onClick = onOpenServerSettings) {
                        Text("Server Settings")
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ChatHistorySheet(
    sessions: List<ChatSession>,
    activeSessionId: String?,
    onSelectSession: (ChatSession) -> Unit,
    onDeleteSession: (ChatSession) -> Unit,
    onNewChat: () -> Unit,
    onDismiss: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp)
                .padding(bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "Previous Chats",
                    style = MaterialTheme.typography.titleLarge,
                )
                TextButton(onClick = onNewChat) {
                    Icon(Icons.Filled.AddComment, contentDescription = null, modifier = Modifier.size(18.dp))
                    Spacer(modifier = Modifier.width(6.dp))
                    Text("New Chat")
                }
            }
            HorizontalDivider()

            if (sessions.isEmpty()) {
                Text(
                    text = "No saved chat sessions yet.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(vertical = 16.dp),
                )
            } else {
                LazyColumn(
                    modifier = Modifier.height(320.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(sessions, key = { it.id }) { session ->
                        val isActive = session.id == activeSessionId
                        Surface(
                            onClick = { onSelectSession(session) },
                            shape = MaterialTheme.shapes.medium,
                            color = if (isActive) {
                                MaterialTheme.colorScheme.primaryContainer
                            } else {
                                MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.45f)
                            },
                            border = BorderStroke(
                                width = if (isActive) 1.5.dp else 1.dp,
                                color = if (isActive) {
                                    MaterialTheme.colorScheme.primary
                                } else {
                                    MaterialTheme.colorScheme.outlineVariant
                                },
                            ),
                        ) {
                            Row(
                                modifier = Modifier
                                    .fillMaxWidth()
                                    .padding(horizontal = 12.dp, vertical = 10.dp),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Column(modifier = Modifier.weight(1f)) {
                                    Text(
                                        text = session.title,
                                        style = MaterialTheme.typography.titleSmall.copy(
                                            fontFamily = DevanagariFontFamily,
                                            fontWeight = if (isActive) FontWeight.Bold else FontWeight.Medium,
                                        ),
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                    Text(
                                        text = "${session.zoneName} • ${session.divisionName} • ${session.departmentName} • " +
                                            DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT)
                                                .format(Date(session.updatedAtMillis)),
                                        style = MaterialTheme.typography.labelSmall,
                                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                                        maxLines = 1,
                                        overflow = TextOverflow.Ellipsis,
                                    )
                                }
                                IconButton(onClick = { onDeleteSession(session) }) {
                                    Icon(
                                        imageVector = Icons.Filled.DeleteOutline,
                                        contentDescription = "Delete chat",
                                        tint = MaterialTheme.colorScheme.onSurfaceVariant,
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
