import CoreVideo
import Foundation

/// Swift interoperability skeleton for copying an NVE-owned pixel buffer before
/// recycleOutput. Preview, recording, RTC, and other asynchronous consumers may
/// reuse this spelling when their existing API does not synchronously retain or
/// copy the buffer. The ownership contract itself is language independent.
final class NVEPixelBufferCopier {
    enum CopyError: Error {
        case allocation
        case lock
        case incompatiblePlanes
    }

    private var pool: CVPixelBufferPool?
    private var signature: (width: Int, height: Int, format: OSType)?

    func copy(_ source: CVPixelBuffer) throws -> CVPixelBuffer {
        let width = CVPixelBufferGetWidth(source)
        let height = CVPixelBufferGetHeight(source)
        let format = CVPixelBufferGetPixelFormatType(source)
        if signature?.width != width ||
            signature?.height != height ||
            signature?.format != format {
            try rebuildPool(width: width, height: height, format: format)
        }

        guard let pool else { throw CopyError.allocation }
        var destination: CVPixelBuffer?
        guard CVPixelBufferPoolCreatePixelBuffer(
            kCFAllocatorDefault,
            pool,
            &destination
        ) == kCVReturnSuccess, let destination else {
            throw CopyError.allocation
        }

        guard CVPixelBufferLockBaseAddress(source, .readOnly) == kCVReturnSuccess else {
            throw CopyError.lock
        }
        defer { CVPixelBufferUnlockBaseAddress(source, .readOnly) }
        guard CVPixelBufferLockBaseAddress(destination, []) == kCVReturnSuccess else {
            throw CopyError.lock
        }
        defer { CVPixelBufferUnlockBaseAddress(destination, []) }

        let planeCount = CVPixelBufferGetPlaneCount(source)
        guard planeCount == CVPixelBufferGetPlaneCount(destination) else {
            throw CopyError.incompatiblePlanes
        }
        if planeCount == 0 {
            try copyRows(
                source: CVPixelBufferGetBaseAddress(source),
                destination: CVPixelBufferGetBaseAddress(destination),
                sourceBytesPerRow: CVPixelBufferGetBytesPerRow(source),
                destinationBytesPerRow: CVPixelBufferGetBytesPerRow(destination),
                height: height
            )
        } else {
            for plane in 0 ..< planeCount {
                try copyRows(
                    source: CVPixelBufferGetBaseAddressOfPlane(source, plane),
                    destination: CVPixelBufferGetBaseAddressOfPlane(destination, plane),
                    sourceBytesPerRow: CVPixelBufferGetBytesPerRowOfPlane(source, plane),
                    destinationBytesPerRow: CVPixelBufferGetBytesPerRowOfPlane(
                        destination,
                        plane
                    ),
                    height: CVPixelBufferGetHeightOfPlane(source, plane)
                )
            }
        }
        CVBufferPropagateAttachments(source, destination)
        return destination
    }

    private func rebuildPool(width: Int, height: Int, format: OSType) throws {
        let attributes: [CFString: Any] = [
            kCVPixelBufferWidthKey: width,
            kCVPixelBufferHeightKey: height,
            kCVPixelBufferPixelFormatTypeKey: format,
            kCVPixelBufferIOSurfacePropertiesKey: [:]
        ]
        var newPool: CVPixelBufferPool?
        guard CVPixelBufferPoolCreate(
            kCFAllocatorDefault,
            nil,
            attributes as CFDictionary,
            &newPool
        ) == kCVReturnSuccess else {
            throw CopyError.allocation
        }
        pool = newPool
        signature = (width, height, format)
    }

    private func copyRows(
        source: UnsafeMutableRawPointer?,
        destination: UnsafeMutableRawPointer?,
        sourceBytesPerRow: Int,
        destinationBytesPerRow: Int,
        height: Int
    ) throws {
        guard let source, let destination else { throw CopyError.lock }
        let byteCount = min(sourceBytesPerRow, destinationBytesPerRow)
        for row in 0 ..< height {
            memcpy(
                destination.advanced(by: row * destinationBytesPerRow),
                source.advanced(by: row * sourceBytesPerRow),
                byteCount
            )
        }
    }
}
