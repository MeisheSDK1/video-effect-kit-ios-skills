import AVFoundation
import Foundation

/// Swift interoperability skeleton for the language-independent latest-state
/// handoff. UI events overwrite one pending snapshot; the stable serial frame
/// callback consumes at most one snapshot immediately before rendering.
///
/// `State` belongs to the customer effect owner. It can represent beauty,
/// makeup, filters, props, or a combined effect graph.
final class NVELatestStateBox<State>: @unchecked Sendable {
    private let lock = NSLock()
    private var desiredState: State
    private var pendingState: State?

    init(initialState: State) {
        desiredState = initialState
        // The first rendered frame must apply non-zero product defaults before
        // the user performs any UI interaction.
        pendingState = initialState
    }

    func publish(_ state: State) {
        lock.lock()
        desiredState = state
        pendingState = state
        lock.unlock()
    }

    func snapshotDesired() -> State {
        lock.lock()
        defer { lock.unlock() }
        return desiredState
    }

    /// Call only on the stable serial render queue, once per input frame.
    func consumeLatest() -> State? {
        lock.lock()
        defer { lock.unlock() }
        let state = pendingState
        pendingState = nil
        return state
    }
}

/// Prevent in-flight old-camera frames from observing a newly committed camera
/// position. The capture/session owner remains responsible for configuration.
final class NVECameraTransitionState: @unchecked Sendable {
    private let lock = NSLock()
    private var position: AVCaptureDevice.Position
    private var transitioning = false

    init(initialPosition: AVCaptureDevice.Position) {
        position = initialPosition
    }

    func begin() {
        lock.lock()
        transitioning = true
        lock.unlock()
    }

    /// The frame callback drops a frame when this returns nil.
    func snapshotIsFrontCamera() -> Bool? {
        lock.lock()
        defer { lock.unlock() }
        return transitioning ? nil : position == .front
    }

    /// After capture configuration commits, invalidate the preview generation,
    /// then call this method. The barrier runs after old frame callbacks that
    /// were already queued on the same render queue.
    func finish(
        committedPosition: AVCaptureDevice.Position,
        on renderQueue: DispatchQueue,
        completion: @escaping @Sendable () -> Void = {}
    ) {
        renderQueue.async { [weak self] in
            guard let self else { return }
            self.lock.lock()
            self.position = committedPosition
            self.transitioning = false
            self.lock.unlock()
            completion()
        }
    }
}
