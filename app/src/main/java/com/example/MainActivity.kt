package com.example

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.example.ui.admin.AdminScreen
import com.example.ui.admin.AdminViewModel
import com.example.ui.auth.AuthScreen
import com.example.ui.auth.AuthViewModel
import com.example.ui.chat.ChatScreen
import com.example.ui.chat.ChatViewModel
import com.example.ui.opening.OpeningScreen
import com.example.ui.opening.OpeningViewModel
import com.example.ui.theme.RailwayRulesTheme

object Routes {
    const val OPENING = "opening"
    const val CHAT = "chat"
    const val ACCOUNT = "account"
    const val ADMIN = "admin"
}

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        val container = (application as RailwayRulesApp).container

        setContent {
            RailwayRulesTheme {
                val navController = rememberNavController()
                val openingViewModel: OpeningViewModel = viewModel(
                    factory = OpeningViewModel.Factory(
                        taxonomyRepository = container.taxonomyRepository,
                        authRepository = container.authRepository,
                        preferences = container.preferences,
                    ),
                )
                val chatViewModel: ChatViewModel = viewModel(
                    factory = ChatViewModel.Factory(
                        chatRepository = container.chatRepository,
                        taxonomyRepository = container.taxonomyRepository,
                        preferences = container.preferences,
                    ),
                )

                NavHost(
                    navController = navController,
                    startDestination = Routes.OPENING,
                ) {
                    composable(Routes.OPENING) {
                        OpeningScreen(
                            viewModel = openingViewModel,
                            onOpenChat = { zone, division, department ->
                                chatViewModel.initializeScope(zone, division, department)
                                navController.navigate(Routes.CHAT)
                            },
                            onOpenAccount = { navController.navigate(Routes.ACCOUNT) },
                            onOpenAdmin = { navController.navigate(Routes.ADMIN) },
                        )
                    }

                    composable(Routes.CHAT) {
                        ChatScreen(
                            viewModel = chatViewModel,
                            onNavigateBack = { navController.popBackStack() },
                        )
                    }

                    composable(Routes.ACCOUNT) {
                        val authViewModel: AuthViewModel = viewModel(
                            factory = AuthViewModel.Factory(container.authRepository),
                        )
                        AuthScreen(
                            viewModel = authViewModel,
                            onNavigateBack = { navController.popBackStack() },
                        )
                    }

                    composable(Routes.ADMIN) {
                        val adminViewModel: AdminViewModel = viewModel(
                            factory = AdminViewModel.Factory(
                                adminRepository = container.adminRepository,
                                authRepository = container.authRepository,
                                taxonomyRepository = container.taxonomyRepository,
                            ),
                        )
                        AdminScreen(
                            viewModel = adminViewModel,
                            onNavigateBack = { navController.popBackStack() },
                            onOpenAccount = { navController.navigate(Routes.ACCOUNT) },
                        )
                    }
                }
            }
        }
    }
}
