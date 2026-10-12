//
//  What the agent would report right now, refreshed every few seconds for the Run tab.
//  Everything here is readable without root.
//

import Foundation
import PulseAgentCore

@Observable
@MainActor
final class LiveState {
    private(set) var snapshot = SessionReader.snapshot()
    private(set) var lastSend = SendResult.load()
    private(set) var hostname = DeviceInfo.hostname()
    private(set) var serial = DeviceInfo.serial()
    private var task: Task<Void, Never>?

    func start() {
        guard task == nil else { return }
        task = Task { [weak self] in
            while !Task.isCancelled {
                self?.refresh()
                try? await Task.sleep(for: .seconds(3))
            }
        }
    }

    func stop() {
        task?.cancel()
        task = nil
    }

    func refresh() {
        snapshot = SessionReader.snapshot()
        lastSend = SendResult.load()
    }
}
