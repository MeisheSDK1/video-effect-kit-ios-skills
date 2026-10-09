import Foundation
import NveEffectKit

/// Compile-checked Swift spellings for Objective-C APIs whose imported names or
/// closure lifetime are easy to infer incorrectly. This is not a second session
/// implementation: keep lifecycle, queueing, render-input construction, and
/// feature state in the customer's existing owner, following the shared contract.
enum NVESwiftSDKInterop {
    enum InteropError: Error {
        case missingModel(Int)
        case modelInitialization(Int)
        case facePropCreation(String)
        case render(Int)
    }

    /// Objective-C `propWithPackageId:` imports as this failable initializer in
    /// NveEffectKit 3.16.1 Swift, not as `prop(withPackageId:)`.
    static func makeFaceProp(packageID: String) throws -> NveFaceProp {
        guard let prop = NveFaceProp(packageId: packageID) else {
            throw InteropError.facePropCreation(packageID)
        }
        return prop
    }

    /// Call only after `verifySdkLicenseFile` succeeds and before `shareInstance`.
    /// The caller owns process-wide caching and supplies only required models.
    static func initializeModels(
        _ modelURLs: [NveDetectionModelType: URL]
    ) throws {
        for (type, url) in modelURLs.sorted(by: { $0.key.rawValue < $1.key.rawValue }) {
            guard FileManager.default.fileExists(atPath: url.path) else {
                throw InteropError.missingModel(type.rawValue)
            }
            guard NveEffectKit.initHumanDetection(
                type,
                modelPath: url.path,
                licenseFilePath: nil
            ) else {
                throw InteropError.modelInitialization(type.rawValue)
            }
        }
    }

    /// The output and its payload are valid only inside `body`, unless `body`
    /// establishes a caller-owned copy/retain/lease before returning.
    static func withRenderOutput(
        effectKit: NveEffectKit,
        input: NveRenderInput,
        body: (NveRenderOutput) throws -> Void
    ) throws {
        let output = effectKit.renderEffect(input)
        // Objective-C `recycleOutput:` imports into Swift as `recycle(_:)`.
        defer { effectKit.recycle(output) }
        guard output.errorCode == .noError else {
            throw InteropError.render(output.errorCode.rawValue)
        }
        try body(output)
    }
}
