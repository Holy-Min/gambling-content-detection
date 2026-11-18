import Foundation
import Vision
import ImageIO

// 인자: 이미지 경로들. 표준출력: 경로당 JSON 한 줄.
// --languages: 지원 인식 언어 목록 출력 후 종료.
if CommandLine.arguments.contains("--languages") {
    let r = VNRecognizeTextRequest()
    r.recognitionLevel = .accurate
    print((try? r.supportedRecognitionLanguages()) ?? [])
    exit(0)
}

func emit(_ obj: [String: Any]) {
    let data = try! JSONSerialization.data(withJSONObject: obj, options: [])
    print(String(data: data, encoding: .utf8)!)
}

for path in CommandLine.arguments.dropFirst() {
    let start = Date()
    var lines: [[String: Any]] = []
    if let src = CGImageSourceCreateWithURL(URL(fileURLWithPath: path) as CFURL, nil),
       let img = CGImageSourceCreateImageAtIndex(src, 0, nil) {
        let req = VNRecognizeTextRequest()
        req.recognitionLevel = .accurate
        req.recognitionLanguages = ["ko-KR", "en-US"]
        req.usesLanguageCorrection = true
        let handler = VNImageRequestHandler(cgImage: img, options: [:])
        try? handler.perform([req])
        for obs in req.results ?? [] {
            guard let top = obs.topCandidates(1).first else { continue }
            let b = obs.boundingBox
            lines.append([
                "text": top.string,
                "conf": Double(top.confidence),
                "box": [Double(b.origin.x), Double(b.origin.y), Double(b.size.width), Double(b.size.height)],
            ])
        }
    }
    let ms = max(Date().timeIntervalSince(start) * 1000, 0.001)
    emit(["path": path, "lines": lines, "ms": ms])
}
