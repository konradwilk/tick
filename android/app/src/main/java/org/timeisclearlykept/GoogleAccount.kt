package org.timeisclearlykept

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import com.google.android.gms.auth.api.identity.AuthorizationRequest
import com.google.android.gms.auth.api.identity.AuthorizationResult
import com.google.android.gms.auth.api.identity.Identity
import com.google.android.gms.common.api.Scope
import com.google.android.gms.tasks.Tasks
import java.util.concurrent.TimeUnit

internal class GoogleAuthorizationRequired(val pendingIntent: PendingIntent) : IllegalStateException("Sign in with Google in Settings to reconnect your spreadsheet.")
internal class GoogleAccount(context: Context) {
    private val client = Identity.getAuthorizationClient(context)
    private var token: String? = null
    private var expires = 0L
    @Synchronized fun authorize(): String {
        val request = AuthorizationRequest.builder().setRequestedScopes(listOf(Scope(SCOPE))).build()
        val result = Tasks.await(client.authorize(request), 35, TimeUnit.SECONDS)
        if (result.hasResolution()) throw GoogleAuthorizationRequired(requireNotNull(result.pendingIntent))
        return accept(result)
    }
    @Synchronized fun accept(intent: Intent?): String = accept(client.getAuthorizationResultFromIntent(intent))
    private fun accept(result: AuthorizationResult): String {
        check(result.grantedScopes.contains(SCOPE)) { "Google Sheets permission was not granted." }
        token = requireNotNull(result.accessToken) { "Google did not grant access." }
        expires = System.currentTimeMillis() + 45 * 60 * 1000
        return token!!
    }
    @Synchronized fun accessToken(): String = if (token != null && expires > System.currentTimeMillis()) token!! else authorize()
    companion object { const val SCOPE = "https://www.googleapis.com/auth/drive.file" }
}
