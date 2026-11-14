package com.example.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

private val LightColorScheme = lightColorScheme(
    primary = RailNavy,
    onPrimary = Color.White,
    primaryContainer = RailNavyContainer,
    onPrimaryContainer = RailOnNavyContainer,
    secondary = RailCrimson,
    onSecondary = Color.White,
    secondaryContainer = RailCrimsonContainer,
    onSecondaryContainer = RailOnCrimsonContainer,
    tertiary = RailBrass,
    onTertiary = Color.White,
    tertiaryContainer = RailBrassContainer,
    onTertiaryContainer = RailOnBrassContainer,
    background = RailPaper,
    onBackground = RailInk,
    surface = RailSurface,
    onSurface = RailInk,
    surfaceVariant = RailSurfaceVariant,
    onSurfaceVariant = RailInkMuted,
    outline = RailOutline,
    outlineVariant = RailOutlineVariant,
    error = RailCrimson,
    onError = Color.White,
)

private val DarkColorScheme = darkColorScheme(
    primary = RailDarkPrimary,
    onPrimary = RailDarkOnPrimary,
    primaryContainer = RailDarkPrimaryContainer,
    onPrimaryContainer = RailDarkInk,
    secondary = RailDarkSecondary,
    onSecondary = Color(0xFF690005),
    secondaryContainer = Color(0xFF7D1916),
    onSecondaryContainer = RailCrimsonContainer,
    tertiary = RailDarkTertiary,
    onTertiary = Color(0xFF3E2900),
    tertiaryContainer = Color(0xFF5A3D00),
    onTertiaryContainer = RailBrassContainer,
    background = RailDarkBackground,
    onBackground = RailDarkInk,
    surface = RailDarkSurface,
    onSurface = RailDarkInk,
    surfaceVariant = RailDarkSurfaceVariant,
    onSurfaceVariant = RailDarkInkMuted,
    outline = RailDarkOutline,
    outlineVariant = Color(0xFF243652),
)

val RailwayShapes = Shapes(
    small = RoundedCornerShape(8.dp),
    medium = RoundedCornerShape(14.dp),
    large = RoundedCornerShape(20.dp),
    extraLarge = RoundedCornerShape(26.dp),
)

@Composable
fun RailwayRulesTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val colorScheme = if (darkTheme) DarkColorScheme else LightColorScheme
    MaterialTheme(
        colorScheme = colorScheme,
        typography = RailwayTypography,
        shapes = RailwayShapes,
        content = content,
    )
}
