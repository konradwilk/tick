import Foundation
import Security
import CryptoKit
import AuthenticationServices
#if os(macOS)
import AppKit
import Network
#else
import UIKit
#endif

public enum GoogleClients {
    public static let desktop = "1048312430782-hprvc7al4c9mvfkqgv9cujns0hilees7.apps.googleusercontent.com"
    public static let ios = "1048312430782-7n70j6sllauv377l4mlo37hu4mi81uqf.apps.googleusercontent.com"
    public static let scope = "https://www.googleapis.com/auth/drive.file"
}
public enum SheetsError: LocalizedError {
    case message(String)
    public var errorDescription: String? { if case .message(let text) = self { return text }; return nil }
}

// Shared synchronous storage contract; network completions use URLSession's worker queue.
enum GoogleHTTP {
    final class Box: @unchecked Sendable { var result: Result<Data, Swift.Error>? }
    static func send(_ request: URLRequest) throws -> Data {
        let box = Box(), semaphore = DispatchSemaphore(value: 0)
        let session = URLSession(configuration: .ephemeral)
        let task = session.dataTask(with: request) { bytes, response, error in
            if let error { box.result = .failure(error) }
            else if let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode), let bytes { box.result = .success(bytes) }
            else { box.result = .failure(SheetsError.message("Google could not authorize or confirm the request. Reconnect, then reload before retrying a save.")) }
            semaphore.signal()
        }
        task.resume()
        guard semaphore.wait(timeout: .now() + 35) == .success else {
            task.cancel(); session.invalidateAndCancel()
            throw SheetsError.message("Google timed out. Reload before retrying a save.")
        }
        session.finishTasksAndInvalidate()
        return try box.result!.get()
    }
    static func form(_ fields: [String: String]) -> Data {
        var query = URLComponents()
        query.queryItems = fields.map { URLQueryItem(name: $0.key, value: $0.value) }
        return Data(query.percentEncodedQuery!.replacingOccurrences(of: "+", with: "%2B").utf8)
    }
}

public final class GoogleAccount: @unchecked Sendable {
    private let lock = NSLock()
    private var token: String?
    private var expires = Date.distantPast
    private static let service = "org.timeisclearlykept.google"
    private static var clientID: String {
        #if os(macOS)
        GoogleClients.desktop
        #else
        GoogleClients.ios
        #endif
    }
    public init() {}
    private static var keyQuery: [String: Any] { [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service, kSecAttrAccount as String: "Tick"] }
    private func refreshToken() throws -> String {
        var query = Self.keyQuery
        query[kSecReturnData as String] = true
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess, let data = result as? Data, let value = String(data: data, encoding: .utf8) else {
            throw SheetsError.message("Sign in with Google in Settings to reconnect your spreadsheet.")
        }
        return value
    }
    private func saveRefresh(_ value: String) throws {
        let data = Data(value.utf8)
        let status = SecItemUpdate(Self.keyQuery as CFDictionary, [kSecValueData as String: data] as CFDictionary)
        if status == errSecItemNotFound {
            var item = Self.keyQuery
            item[kSecValueData as String] = data
            item[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
            guard SecItemAdd(item as CFDictionary, nil) == errSecSuccess else { throw SheetsError.message("Could not save Google sign-in in Keychain.") }
        } else if status != errSecSuccess { throw SheetsError.message("Could not update Google sign-in in Keychain.") }
    }
    private func exchange(_ fields: [String: String]) throws -> [String: Any] {
        var fields = fields
        #if os(macOS)
        fields["client_secret"] = GoogleDesktopClient.secret
        #endif
        var request = URLRequest(url: URL(string: "https://oauth2.googleapis.com/token")!)
        request.httpMethod = "POST"; request.timeoutInterval = 30
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        request.httpBody = GoogleHTTP.form(fields)
        guard let result = try JSONSerialization.jsonObject(with: GoogleHTTP.send(request)) as? [String: Any], let access = result["access_token"] as? String else { throw SheetsError.message("Google sign-in failed. Try again.") }
        if let scope = result["scope"] as? String, !scope.split(separator: " ").contains(Substring(GoogleClients.scope)) { throw SheetsError.message("Google Sheets permission was not granted.") }
        token = access; expires = Date().addingTimeInterval((result["expires_in"] as? Double ?? 3600) - 60)
        return result
    }
    public func accessToken() throws -> String {
        lock.lock(); defer { lock.unlock() }
        let refresh = try refreshToken()
        if let token, expires > Date() { return token }
        _ = try exchange(["client_id": Self.clientID, "grant_type": "refresh_token", "refresh_token": refresh])
        return token!
    }
    public func signOut() throws {
        lock.lock(); defer { lock.unlock() }
        let status = SecItemDelete(Self.keyQuery as CFDictionary)
        guard status == errSecSuccess || status == errSecItemNotFound else { throw SheetsError.message("Could not remove Google sign-in from Keychain.") }
        token = nil; expires = .distantPast
    }
    @MainActor public func signIn() async throws {
        var bytes = [UInt8](repeating: 0, count: 64)
        guard SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes) == errSecSuccess else { throw SheetsError.message("Could not start secure sign-in.") }
        let verifier = Data(bytes).base64EncodedString().urlSafe
        let challenge = Data(SHA256.hash(data: Data(verifier.utf8))).base64EncodedString().urlSafe
        let state = UUID().uuidString + UUID().uuidString
        let makeURL: @Sendable (String) -> URL = { redirect in
            let fields = ["client_id": Self.clientID, "redirect_uri": redirect, "response_type": "code", "scope": GoogleClients.scope,
                          "code_challenge": challenge, "code_challenge_method": "S256", "state": state, "access_type": "offline", "prompt": "consent select_account"]
            return URL(string: "https://accounts.google.com/o/oauth2/v2/auth?" + String(data: GoogleHTTP.form(fields), encoding: .utf8)!)!
        }
        let code: String, redirect: String
        #if os(macOS)
        (code, redirect) = try await LoopbackAuthorization.run(state: state, makeURL: makeURL)
        #else
        redirect = "com.googleusercontent.apps.1048312430782-7n70j6sllauv377l4mlo37hu4mi81uqf:/oauthredirect"
        let presenter = GoogleAuthPresenter()
        let callback = try await presenter.authorize(url: makeURL(redirect), scheme: "com.googleusercontent.apps.1048312430782-7n70j6sllauv377l4mlo37hu4mi81uqf")
        code = try authorizationCode(callback, state: state)
        #endif
        try await Task.detached { [self] in
            try lock.withLock {
                let result = try exchange(["client_id": Self.clientID, "grant_type": "authorization_code", "code": code, "redirect_uri": redirect, "code_verifier": verifier])
                guard let refresh = result["refresh_token"] as? String else { throw SheetsError.message("Google did not return a persistent sign-in. Try again.") }
                try saveRefresh(refresh)
            }
        }.value
    }
}
private extension String { var urlSafe: String { replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "") } }
func authorizationCode(_ url: URL, state: String) throws -> String {
    let fields = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
    guard fields.first(where: { $0.name == "state" })?.value == state else { throw SheetsError.message("Invalid Google sign-in response.") }
    guard let code = fields.first(where: { $0.name == "code" })?.value, !code.isEmpty else { throw SheetsError.message("Google sign-in was cancelled or denied.") }
    return code
}
#if os(macOS)
private final class LoopbackAuthorization: @unchecked Sendable {
    private let lock = NSLock()
    private var completion: CheckedContinuation<(String, String), Swift.Error>?
    private var listener: NWListener?
    private var redirect = ""
    static func run(state: String, makeURL: @escaping @Sendable (String) -> URL) async throws -> (String, String) {
        let receiver = LoopbackAuthorization()
        return try await withCheckedThrowingContinuation { continuation in
            receiver.completion = continuation
            do {
                let parameters = NWParameters.tcp
                parameters.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: .any)
                let listener = try NWListener(using: parameters)
                receiver.listener = listener
                listener.stateUpdateHandler = { status in
                    if case .ready = status, let port = listener.port {
                        receiver.redirect = "http://127.0.0.1:\(port.rawValue)/oauth2callback"
                        let url = makeURL(receiver.redirect)
                        DispatchQueue.main.async { if !NSWorkspace.shared.open(url) { receiver.finish(.failure(SheetsError.message("Could not open your browser."))) } }
                    } else if case .failed(let error) = status { receiver.finish(.failure(error)) }
                }
                listener.newConnectionHandler = { connection in
                    connection.start(queue: .global())
                    receiver.receive(connection, buffer: Data(), state: state)
                }
                listener.start(queue: .global())
                DispatchQueue.global().asyncAfter(deadline: .now() + 180) { receiver.finish(.failure(SheetsError.message("Google sign-in timed out. Try again."))) }
            } catch { receiver.finish(.failure(error)) }
        }
    }
    private func receive(_ connection: NWConnection, buffer: Data, state: String) {
        connection.receive(minimumIncompleteLength: 1, maximumLength: 16384) { [self] data, _, complete, error in
            var buffer = buffer; if let data { buffer.append(data) }
            guard buffer.count < 32768, error == nil else { connection.cancel(); return }
            guard let text = String(data: buffer, encoding: .utf8), text.contains("\r\n\r\n") else {
                if complete { connection.cancel() } else { receive(connection, buffer: buffer, state: state) }; return
            }
            let path = text.components(separatedBy: " ").dropFirst().first ?? ""
            let url = URL(string: "http://127.0.0.1" + path)
            guard let url, url.path == "/oauth2callback" else { connection.cancel(); return }
            guard URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems?.first(where: { $0.name == "state" })?.value == state else {
                connection.send(content: Data("HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\nInvalid callback.".utf8), completion: .contentProcessed { _ in connection.cancel() }); return
            }
            let result = Result { (try authorizationCode(url, state: state), redirect) }
            let response = Data("HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nConnection: close\r\n\r\nReturn to Tick to finish connecting Google Sheets.".utf8)
            connection.send(content: response, completion: .contentProcessed { _ in connection.cancel(); self.finish(result) })
        }
    }
    private func finish(_ result: Result<(String, String), Swift.Error>) {
        lock.lock(); let completion = completion; self.completion = nil; lock.unlock()
        let listener = listener; self.listener = nil
        listener?.stateUpdateHandler = nil; listener?.newConnectionHandler = nil; listener?.cancel()
        completion?.resume(with: result)
    }
}
#else
@MainActor private final class GoogleAuthPresenter: NSObject, ASWebAuthenticationPresentationContextProviding {
    private var session: ASWebAuthenticationSession?
    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.flatMap(\.windows).first(where: \.isKeyWindow) ?? ASPresentationAnchor()
    }
    func authorize(url: URL, scheme: String) async throws -> URL {
        try await withCheckedThrowingContinuation { continuation in
            let session = ASWebAuthenticationSession(url: url, callbackURLScheme: scheme) { url, error in
                if let url { continuation.resume(returning: url) }
                else { continuation.resume(throwing: error ?? SheetsError.message("Google sign-in was cancelled.")) }
            }
            self.session = session; session.presentationContextProvider = self
            if !session.start() { continuation.resume(throwing: SheetsError.message("Could not start Google sign-in.")) }
        }
    }
}
#endif
