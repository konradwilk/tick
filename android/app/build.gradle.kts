plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("org.jetbrains.kotlin.plugin.serialization")
}
val sourceVersion = providers.exec {
    commandLine(if (System.getProperty("os.name").startsWith("Windows")) "python" else "python3",
        rootProject.file("../linux/tick/version.py").absolutePath)
}.standardOutput.asText.get().trim()
android {
    namespace = "org.timeisclearlykept"
    compileSdk = 35
    defaultConfig {
        applicationId = "org.timeisclearlykept"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = sourceVersion
    }
    // Keep locally registered Google OAuth debug signing stable; never commit the keystore.
    val localDebugKey = rootProject.file("../tick-credentials/android-debug.keystore")
    if (localDebugKey.isFile) {
        signingConfigs.getByName("debug") {
            storeFile = localDebugKey
            storePassword = "android"
            keyAlias = "androiddebugkey"
            keyPassword = "android"
        }
    }
    sourceSets.getByName("test").resources.srcDir("../../fixtures")
    buildFeatures { compose = true; buildConfig = true }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}
dependencies {
    implementation("com.google.android.gms:play-services-auth:22.0.0")
    implementation(platform("androidx.compose:compose-bom:2025.04.01"))
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.8.1")
    testImplementation("junit:junit:4.13.2")
}
