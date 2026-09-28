import Foundation
import Vision
import ImageIO

// Local OCR for document screenshots; no model or network credentials are used.
do {
    guard CommandLine.arguments.count == 2 else {
        throw NSError(domain: "OCR", code: 1, userInfo: [NSLocalizedDescriptionKey: "Expected an image path"])
    }
    let url = URL(fileURLWithPath: CommandLine.arguments[1])
    guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
          let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
          let width = properties[kCGImagePropertyPixelWidth] as? Int,
          let height = properties[kCGImagePropertyPixelHeight] as? Int,
          width > 0, height > 0, width <= 16000, height <= 16000,
          width * height <= 32_000_000 else {
        throw NSError(domain: "OCR", code: 2, userInfo: [NSLocalizedDescriptionKey: "Invalid image or image exceeds 32 megapixels / 16000 pixels per side"])
    }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "zh-Hant", "en-US"]
    request.usesLanguageCorrection = false
    try VNImageRequestHandler(url: url).perform([request])
    let lines = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
    let data = try JSONSerialization.data(withJSONObject: ["text": lines.joined(separator: "\n")])
    FileHandle.standardOutput.write(data)
} catch {
    FileHandle.standardError.write(Data(error.localizedDescription.utf8))
    exit(1)
}
