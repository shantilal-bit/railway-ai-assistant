package com.example.ui.components

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.ExpandLess
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material.icons.filled.Gavel
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.MenuBook
import androidx.compose.material.icons.filled.Schedule
import androidx.compose.material.icons.filled.WarningAmber
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.example.domain.model.SourceCitation
import com.example.domain.model.StructuredRuleAnswer
import com.example.ui.theme.RailSignalGreen
import com.example.ui.theme.RailSignalGreenContainer
import com.example.ui.theme.fontFamilyForText

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun StructuredAnswerCard(
    answer: StructuredRuleAnswer,
    onCopyAnswer: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    var showSources by rememberSaveable { mutableStateOf(true) }

    Card(
        modifier = modifier
            .fillMaxWidth()
            .testTag("structured_answer_card"),
        shape = MaterialTheme.shapes.large,
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
        elevation = CardDefaults.cardElevation(defaultElevation = 1.dp),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            // Top Status + Copy Row
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Surface(
                    shape = RoundedCornerShape(999.dp),
                    color = if (answer.isReliableAnswerFound) {
                        RailSignalGreenContainer
                    } else {
                        MaterialTheme.colorScheme.tertiaryContainer
                    },
                ) {
                    Row(
                        modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(
                            imageVector = if (answer.isReliableAnswerFound) {
                                Icons.Filled.CheckCircle
                            } else {
                                Icons.Filled.Info
                            },
                            contentDescription = null,
                            tint = if (answer.isReliableAnswerFound) {
                                RailSignalGreen
                            } else {
                                MaterialTheme.colorScheme.onTertiaryContainer
                            },
                            modifier = Modifier.size(16.dp),
                        )
                        Spacer(modifier = Modifier.width(6.dp))
                        Text(
                            text = if (answer.isReliableAnswerFound) {
                                "Official Rule Reference"
                            } else {
                                "No Reliable Record Found"
                            },
                            style = MaterialTheme.typography.labelMedium,
                            color = if (answer.isReliableAnswerFound) {
                                RailSignalGreen
                            } else {
                                MaterialTheme.colorScheme.onTertiaryContainer
                            },
                        )
                    }
                }

                IconButton(
                    onClick = { onCopyAnswer(formatAnswerForCopy(answer)) },
                    modifier = Modifier.testTag("copy_answer_button"),
                ) {
                    Icon(
                        imageVector = Icons.Filled.ContentCopy,
                        contentDescription = "Copy structured answer",
                        tint = MaterialTheme.colorScheme.primary,
                    )
                }
            }

            // Conflict / Supersession Alert
            if (!answer.conflictWarning.isNullOrBlank()) {
                Spacer(modifier = Modifier.height(10.dp))
                Surface(
                    shape = MaterialTheme.shapes.medium,
                    color = MaterialTheme.colorScheme.secondaryContainer,
                    border = BorderStroke(1.dp, MaterialTheme.colorScheme.secondary.copy(alpha = 0.35f)),
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(12.dp),
                        verticalAlignment = Alignment.Top,
                    ) {
                        Icon(
                            imageVector = Icons.Filled.WarningAmber,
                            contentDescription = "Conflicting instructions notice",
                            tint = MaterialTheme.colorScheme.secondary,
                            modifier = Modifier.size(20.dp),
                        )
                        Spacer(modifier = Modifier.width(10.dp))
                        Column {
                            Text(
                                text = "Conflicting / Superseded Instruction Notice",
                                style = MaterialTheme.typography.labelLarge,
                                color = MaterialTheme.colorScheme.onSecondaryContainer,
                            )
                            Spacer(modifier = Modifier.height(2.dp))
                            Text(
                                text = answer.conflictWarning,
                                style = MaterialTheme.typography.bodySmall.copy(
                                    fontFamily = fontFamilyForText(answer.conflictWarning),
                                ),
                                color = MaterialTheme.colorScheme.onSecondaryContainer,
                            )
                        }
                    }
                }
            }

            Spacer(modifier = Modifier.height(12.dp))

            // 1. Direct Answer
            Text(
                text = "1. Direct Answer",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.primary,
            )
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = answer.directAnswer,
                style = MaterialTheme.typography.titleMedium.copy(
                    fontFamily = fontFamilyForText(answer.directAnswer),
                    fontWeight = FontWeight.SemiBold,
                ),
                color = MaterialTheme.colorScheme.onSurface,
            )

            Spacer(modifier = Modifier.height(12.dp))

            // 2. Detailed Explanation
            Text(
                text = "2. Detailed Explanation",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.primary,
            )
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = answer.detailedExplanation,
                style = MaterialTheme.typography.bodyMedium.copy(
                    fontFamily = fontFamilyForText(answer.detailedExplanation),
                ),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )

            Spacer(modifier = Modifier.height(14.dp))
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
            Spacer(modifier = Modifier.height(12.dp))

            // 3–7 Structured Authority Metadata
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                MetadataLine(
                    icon = Icons.Filled.Gavel,
                    label = "3. Applicable Rule Number",
                    value = answer.applicableRuleNumber,
                )
                MetadataLine(
                    icon = Icons.Filled.MenuBook,
                    label = "4. Official Document Name",
                    value = answer.officialDocumentName,
                )
                MetadataLine(
                    icon = Icons.Filled.Description,
                    label = "5. PDF Page Number",
                    value = answer.pdfPageNumber,
                )
                if (!answer.amendmentOrCircularRef.isNullOrBlank()) {
                    MetadataLine(
                        icon = Icons.Filled.Info,
                        label = "6. Amendment / Circular Reference",
                        value = answer.amendmentOrCircularRef,
                    )
                }
                if (!answer.effectiveDate.isNullOrBlank()) {
                    MetadataLine(
                        icon = Icons.Filled.Schedule,
                        label = "7. Effective Date",
                        value = answer.effectiveDate,
                    )
                }
            }

            // Citations List
            if (answer.citations.isNotEmpty()) {
                Spacer(modifier = Modifier.height(12.dp))
                HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text(
                        text = "Source Documents (${answer.citations.size})",
                        style = MaterialTheme.typography.titleSmall,
                        color = MaterialTheme.colorScheme.onSurface,
                    )
                    TextButton(
                        onClick = { showSources = !showSources },
                        modifier = Modifier.testTag("toggle_sources_button"),
                    ) {
                        Text(if (showSources) "Hide" else "Show")
                        Spacer(modifier = Modifier.width(4.dp))
                        Icon(
                            imageVector = if (showSources) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore,
                            contentDescription = null,
                            modifier = Modifier.size(18.dp),
                        )
                    }
                }

                AnimatedVisibility(visible = showSources) {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        answer.citations.forEach { citation ->
                            SourceCitationItem(citation = citation)
                        }
                    }
                }
            }

            if (!answer.aiProvider.isNullOrBlank()) {
                Spacer(modifier = Modifier.height(10.dp))
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    AssistChip(
                        onClick = {},
                        enabled = false,
                        label = {
                            Text(
                                text = "Provider: ${answer.aiProvider.uppercase()}" +
                                    (answer.modelName?.let { " ($it)" } ?: ""),
                                style = MaterialTheme.typography.labelSmall,
                            )
                        },
                    )
                }
            }
        }
    }
}

@Composable
private fun MetadataLine(
    icon: ImageVector,
    label: String,
    value: String,
) {
    Surface(
        shape = MaterialTheme.shapes.small,
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.55f),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 10.dp, vertical = 8.dp),
            verticalAlignment = Alignment.Top,
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.primary,
                modifier = Modifier
                    .padding(top = 2.dp)
                    .size(16.dp),
            )
            Spacer(modifier = Modifier.width(8.dp))
            Column {
                Text(
                    text = label,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = value,
                    style = MaterialTheme.typography.bodyMedium.copy(
                        fontFamily = fontFamilyForText(value),
                        fontWeight = FontWeight.Medium,
                    ),
                    color = MaterialTheme.colorScheme.onSurface,
                )
            }
        }
    }
}

@Composable
private fun SourceCitationItem(citation: SourceCitation) {
    Surface(
        shape = MaterialTheme.shapes.medium,
        color = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.45f),
        border = BorderStroke(1.dp, MaterialTheme.colorScheme.outlineVariant),
    ) {
        Column(modifier = Modifier.padding(10.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = citation.documentTitle,
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.onSurface,
                    modifier = Modifier.weight(1f),
                )
                Spacer(modifier = Modifier.width(8.dp))
                Surface(
                    shape = RoundedCornerShape(6.dp),
                    color = MaterialTheme.colorScheme.primaryContainer,
                ) {
                    Text(
                        text = "Page ${citation.pageNumber}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onPrimaryContainer,
                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                    )
                }
            }
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = buildString {
                    append("Tier ${citation.searchTier}: ${citation.searchTierLabel}")
                    citation.ruleNumber?.let { append(" • $it") }
                    citation.effectiveDate?.let { append(" • Effective: $it") }
                    if (citation.isSuperseded) append(" • [SUPERSEDED]")
                },
                style = MaterialTheme.typography.labelSmall,
                color = if (citation.isSuperseded) {
                    MaterialTheme.colorScheme.secondary
                } else {
                    MaterialTheme.colorScheme.onSurfaceVariant
                },
            )
            if (citation.excerpt.isNotBlank()) {
                Spacer(modifier = Modifier.height(6.dp))
                Text(
                    text = citation.excerpt,
                    style = MaterialTheme.typography.bodySmall.copy(
                        fontFamily = fontFamilyForText(citation.excerpt),
                    ),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 4,
                )
            }
        }
    }
}

fun formatAnswerForCopy(answer: StructuredRuleAnswer): String = buildString {
    appendLine("1. Direct Answer:")
    appendLine(answer.directAnswer)
    appendLine()
    appendLine("2. Detailed Explanation:")
    appendLine(answer.detailedExplanation)
    appendLine()
    appendLine("3. Applicable Rule Number: ${answer.applicableRuleNumber}")
    appendLine("4. Official Document Name: ${answer.officialDocumentName}")
    appendLine("5. PDF Page Number: ${answer.pdfPageNumber}")
    answer.amendmentOrCircularRef?.let { appendLine("6. Amendment / Circular Reference: $it") }
    answer.effectiveDate?.let { appendLine("7. Effective Date: $it") }
    answer.conflictWarning?.let {
        appendLine()
        appendLine("Conflicting Instructions Note: $it")
    }
}
