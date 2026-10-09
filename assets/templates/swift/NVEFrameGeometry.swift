import AVFoundation
import Foundation
import NveEffectKit

/// Explicitly selects the single owner of pixel-buffer orientation.
///
/// Use `upstreamOriented` for AVCaptureVideoDataOutput when its connection
/// already produces buffers in the product presentation orientation. This is
/// the default real-time camera contract and intentionally leaves the NVE
/// orientation fields untouched.
///
/// `explicitSDKMetadata` is only for a non-standard input whose audited SDK
/// contract requires these fields. Never derive its values from screen size or
/// use it together with a downstream rotation transform.
enum NVEFrameGeometry {
    case upstreamOriented(mirror: Bool)
    /// Use only after a device A/B probe proves that NVE-owned mirroring returns
    /// an all-zero buffer while the capture-mirrored input renders correctly.
    /// The AVCapture connection must be the sole mirror owner for this policy.
    case captureMirrored
    case explicitSDKMetadata(
        mirror: Bool,
        imageOrientation: AVCaptureVideoOrientation,
        displayRotation: Float
    )

    func apply(to imageBuffer: NveImageBuffer) {
        switch self {
        case let .upstreamOriented(mirror):
            imageBuffer.mirror = mirror

        case .captureMirrored:
            imageBuffer.mirror = false

        case let .explicitSDKMetadata(
            mirror,
            imageOrientation,
            displayRotation
        ):
            imageBuffer.mirror = mirror
            imageBuffer.imageOrientation = imageOrientation
            imageBuffer.displayRotation = displayRotation
        }
    }
}
