import Foundation
import IOKit
import IOKit.pwr_mgt

/// Calls back as the Mac goes to sleep and as it wakes, through IORegisterForSystemPower.
/// macOS holds sleep until the sleep callback returns and the change is allowed, so the
/// callback must finish quickly; the system forces sleep after 30 seconds regardless.
public final class PowerWatcher: @unchecked Sendable {
    /// iokit_common_msg values from IOKit/IOMessage.h, which Swift does not import as constants.
    public enum Message: UInt32 {
        case canSystemSleep = 0xE000_0270
        case systemWillSleep = 0xE000_0280
        case systemHasPoweredOn = 0xE000_0300
    }

    private var root: io_connect_t = 0
    private var port: IONotificationPortRef?
    private var notifier: io_object_t = 0
    private let queue = DispatchQueue(label: "managedpresencebeacon.power")
    private let onSleep: @Sendable () -> Void
    private let onWake: @Sendable () -> Void

    /// Registers for sleep and wake, or returns nil when IOKit refuses.
    public init?(onSleep: @escaping @Sendable () -> Void, onWake: @escaping @Sendable () -> Void) {
        self.onSleep = onSleep
        self.onWake = onWake
        let refcon = Unmanaged.passUnretained(self).toOpaque()
        root = IORegisterForSystemPower(refcon, &port, { refcon, _, type, argument in
            guard let refcon else { return }
            Unmanaged<PowerWatcher>.fromOpaque(refcon).takeUnretainedValue().handle(type, argument)
        }, &notifier)
        guard root != 0, let port else { return nil }
        IONotificationPortSetDispatchQueue(port, queue)
    }

    /// The event a power message stands for: sleep, wake, or nothing.
    public static func kind(_ type: UInt32) -> PulseEvent.Kind? {
        switch Message(rawValue: type) {
        case .systemWillSleep: return .sleep
        case .systemHasPoweredOn: return .wake
        default: return nil
        }
    }

    private func handle(_ type: natural_t, _ argument: UnsafeMutableRawPointer?) {
        let token = Int(bitPattern: argument)
        switch Message(rawValue: type) {
        case .canSystemSleep:
            IOAllowPowerChange(root, token)
        case .systemWillSleep:
            onSleep()
            IOAllowPowerChange(root, token)
        case .systemHasPoweredOn:
            onWake()
        case nil:
            break
        }
    }

    deinit {
        if notifier != 0 { IODeregisterForSystemPower(&notifier) }
        if root != 0 { IOServiceClose(root) }
        if let port { IONotificationPortDestroy(port) }
    }
}
