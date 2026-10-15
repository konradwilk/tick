# Google sign-in: new project setup for the Tick maintainer

This is the developer registration for Tick’s direct Google Sheets connection.
End users should not perform these steps. Desktop and iOS client IDs supplied by
the maintainer are bundled; Android still requires signing-certificate registration.

The user flow is **Google Sheets → Sign in with Google → Create or open
a spreadsheet**. The default spreadsheet name remains **Time is Clearly Kept**,
with an editable name in the app and `--name` in the migration tool. No Apps Script
deployment URL or shared access key should be requested in that flow.

## 1. Create the project

Open [Google Cloud project creation](https://console.cloud.google.com/projectcreate).
Use **Time is Clearly Kept** as the display name. Google requires a unique project
ID; accept its suggested ID or choose an available one. Record that ID.

Enable these APIs in the new project's API Library:

- **Google Sheets API**: reading, creating, and writing spreadsheets.
- **Google Drive API**: finding spreadsheets authorized for Tick.
- **Google Picker API**: granting access to an existing spreadsheet through Google's
  file picker when that integration is implemented.

Google Sheets API accepts the per-file `https://www.googleapis.com/auth/drive.file`
scope. Prefer this to requesting access to all of the user's spreadsheets or
all of Drive. Pasting an arbitrary sheet URL does not itself grant per-file access;
existing files must be selected/authorized through the appropriate Google flow.

## 2. Configure Google Auth Platform

In the project's [Google Auth Platform](https://console.cloud.google.com/auth/overview):

1. Under Branding, set the app name to **Time is Clearly Kept**, choose your support
   email, and enter your developer contact email.
2. Choose an External audience if users outside your own Google Workspace
   organization will use Tick. Start in Testing and add your own Google account
   as a test user.
3. Under Data Access, configure the per-file Drive permission above.
4. Before public distribution, complete the applicable branding, consent-screen,
   publishing, and verification requirements shown by Google. Test-mode access
   is not a substitute for a production setup.

Use your own support/contact details and any required privacy-policy and app
homepage URLs. Those cannot be inferred from the repository.

## 3. Register platform clients

Under Clients, create the following OAuth registrations in the **same project**:

| Client | Type | Registration details |
| --- | --- | --- |
| Tick Desktop | Desktop app | Windows, Linux, macOS desktop flow, and Python migration tool |
| Tick iOS | iOS | Bundle ID `org.timeisclearlykept.ios`; Apple team `92X2Q2GS25` if requested and still applicable |
| Tick Android debug | Android | Package `org.timeisclearlykept` and the debug signing certificate SHA-1 |
| Tick Android release | Android | Same package, with the release/app-signing certificate SHA-1 |

The Apple identifiers above come from the current Xcode project. Verify the team
before registering under a different Apple developer account. Android release
certificate fingerprints depend on the actual distribution signing key; they
cannot be substituted with the debug fingerprint. For Play distribution, use
the app-signing certificate appropriate to the installed build.

On a configured Android development machine, run `gradle signingReport` from
`android/` to obtain debug signing details. Release registration can wait until
release signing is configured.

The verified local Android debug build now uses the ignored
`tick-credentials/android-debug.keystore`. For this build, register:

- Package: `org.timeisclearlykept`
- SHA-1: `69:C5:52:55:F5:9C:97:B3:96:65:98:D6:D6:11:7C:8E:09:33:04:C8`

Keep a backup of that development keystore outside the repository. The Gradle
build uses it when present; other machines and CI without it generate a different
debug certificate and need their own registration. Never use this debug key for
production releases. No service-account key or web-server OAuth secret
is needed from users. Desktop client downloads can include a client-secret field;
installed apps cannot treat it as a confidential server secret.

Desktop authorization should use the system browser, PKCE, and a loopback
callback. Mobile clients require the supported native authorization flows;
Google's desktop loopback flow must not be reused for Android/iOS. Android uses
Google's authorization library. iOS uses its platform authorization integration.
Refresh tokens must be kept in each operating system's credential storage rather
than in the shared spreadsheet or portable `tick.json`.

## 4. Registration handoff

The information needed to wire and test the new connection is:

- Google Cloud project ID.
- Desktop OAuth client ID.
- iOS OAuth client ID and its registered bundle ID.
- Android OAuth registration details: package name and signing fingerprints.

Client IDs are public app identifiers. Do not send account passwords, refresh
tokens, service-account private keys, or web-client secrets. If Google Picker
requires an API key for the selected integration, configure its restrictions for
that integration before distribution.

## Packaging and verification

Run `python3 tools/configure_google.py` to package the Desktop installed-app
configuration for Python/Linux. Apple and Windows builds generate it automatically
from the ignored `tick-credentials/` download or
`TICK_GOOGLE_DESKTOP_CLIENT_SECRET`. Only client IDs belong in tracked configuration.
See [packaging and migration](google-sheets.md).

Direct Sheets writes use the retained revision protocol in [the API description](api.md).
There is no Apps Script backend or server lock. A client-side read followed by an
append is not atomic compare-and-swap; concurrent branches are retained and rejected
for recovery. Test cancellation, token expiration/revocation, multiple devices, and
failed/ambiguous saves on each platform before distributing a configured release.

References:

- [Google installed-app OAuth](https://developers.google.com/identity/protocols/oauth2/native-app)
- [Android authorization](https://developer.android.com/identity/authorization)
- [Sheets API scopes](https://developers.google.com/workspace/sheets/api/scopes)
- [Spreadsheet creation](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/create)
- [Google Picker for native apps](https://developers.google.com/workspace/drive/picker/guides/desktop-mobile-picker)
