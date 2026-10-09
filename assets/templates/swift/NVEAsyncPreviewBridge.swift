import AVFoundation
import CoreVideo
import Foundation
import UIKit

/// Swift interoperability skeleton for a capacity-one asynchronous preview.
/// Publish only caller-owned, presentation-ready buffers created before the
/// NVE output is recycled. This view never rotates or mirrors pixels.
struct NVEOwnedPreviewFrame {
    let sampleBuffer: CMSampleBuffer
    let generation: Int
}

/// Capacity-one preview mailbox. Publish only caller-owned buffers, never an
/// NVE output payload that will be recycled before this mailbox drains.
final class NVEPreviewMailbox: @unchecked Sendable {
    private let lock = NSLock()
    private weak var previewView: NVEPreviewView?
    private var pendingFrame: NVEOwnedPreviewFrame?
    private var drainScheduled = false
    private var generation = 0

    @MainActor
    func attach(_ view: NVEPreviewView) {
        previewView = view
    }

    @MainActor
    func detach(_ view: NVEPreviewView) {
        if previewView === view {
            previewView = nil
        }
    }

    /// Use for camera/session/output discontinuities, not slider changes.
    func invalidate(removeCurrentImage: Bool) {
        lock.lock()
        generation += 1
        pendingFrame = nil
        lock.unlock()

        guard removeCurrentImage else { return }
        DispatchQueue.main.async { [weak self] in
            self?.previewView?.flushAndRemoveImage()
        }
    }

    func publish(
        ownedPixelBuffer: CVPixelBuffer,
        sourceSampleBuffer: CMSampleBuffer
    ) {
        guard let sampleBuffer = Self.makeSampleBuffer(
            pixelBuffer: ownedPixelBuffer,
            sourceSampleBuffer: sourceSampleBuffer
        ) else {
            return
        }

        lock.lock()
        pendingFrame = NVEOwnedPreviewFrame(
            sampleBuffer: sampleBuffer,
            generation: generation
        )
        let shouldSchedule = !drainScheduled
        if shouldSchedule {
            drainScheduled = true
        }
        lock.unlock()

        guard shouldSchedule else { return }
        DispatchQueue.main.async { [weak self] in
            self?.drain()
        }
    }

    private func drain() {
        dispatchPrecondition(condition: .onQueue(.main))

        lock.lock()
        let frame = pendingFrame
        pendingFrame = nil
        let currentGeneration = generation
        drainScheduled = false
        lock.unlock()

        if let frame, frame.generation == currentGeneration {
            previewView?.enqueue(frame.sampleBuffer)
        }

        lock.lock()
        let shouldSchedule = pendingFrame != nil && !drainScheduled
        if shouldSchedule {
            drainScheduled = true
        }
        lock.unlock()
        if shouldSchedule {
            DispatchQueue.main.async { [weak self] in
                self?.drain()
            }
        }
    }

    private static func makeSampleBuffer(
        pixelBuffer: CVPixelBuffer,
        sourceSampleBuffer: CMSampleBuffer
    ) -> CMSampleBuffer? {
        var formatDescription: CMVideoFormatDescription?
        guard CMVideoFormatDescriptionCreateForImageBuffer(
            allocator: kCFAllocatorDefault,
            imageBuffer: pixelBuffer,
            formatDescriptionOut: &formatDescription
        ) == noErr, let formatDescription else {
            return nil
        }

        var timing = CMSampleTimingInfo(
            duration: CMSampleBufferGetDuration(sourceSampleBuffer),
            presentationTimeStamp: CMSampleBufferGetPresentationTimeStamp(sourceSampleBuffer),
            decodeTimeStamp: .invalid
        )
        var output: CMSampleBuffer?
        guard CMSampleBufferCreateReadyWithImageBuffer(
            allocator: kCFAllocatorDefault,
            imageBuffer: pixelBuffer,
            formatDescription: formatDescription,
            sampleTiming: &timing,
            sampleBufferOut: &output
        ) == noErr, let output else {
            return nil
        }
        CMSetAttachment(
            output,
            key: kCMSampleAttachmentKey_DisplayImmediately,
            value: kCFBooleanTrue,
            attachmentMode: kCMAttachmentMode_ShouldPropagate
        )
        return output
    }
}

final class NVEPreviewView: UIView {
    override class var layerClass: AnyClass {
        AVSampleBufferDisplayLayer.self
    }

    private var displayLayer: AVSampleBufferDisplayLayer {
        guard let value = layer as? AVSampleBufferDisplayLayer else {
            preconditionFailure("NVEPreviewView requires AVSampleBufferDisplayLayer")
        }
        return value
    }

    override init(frame: CGRect) {
        super.init(frame: frame)
        configure()
    }

    required init?(coder: NSCoder) {
        super.init(coder: coder)
        configure()
    }

    private func configure() {
        displayLayer.videoGravity = .resizeAspectFill
        backgroundColor = .black
        accessibilityIdentifier = "nve.preview"
    }

    /// The frame must already have its final presentation orientation/mirror.
    /// Do not add a view transform here to compensate for capture/NVE geometry.
    func enqueue(_ sampleBuffer: CMSampleBuffer) {
        dispatchPrecondition(condition: .onQueue(.main))
        if displayLayer.status == .failed {
            displayLayer.flushAndRemoveImage()
        }
        guard displayLayer.isReadyForMoreMediaData else { return }
        displayLayer.enqueue(sampleBuffer)
    }

    func flushAndRemoveImage() {
        dispatchPrecondition(condition: .onQueue(.main))
        displayLayer.flushAndRemoveImage()
    }
}
