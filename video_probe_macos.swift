import Foundation
import AVFoundation
import CoreMedia
let asset = AVURLAsset(url: URL(fileURLWithPath: CommandLine.arguments[1]))
let duration = try await asset.load(.duration)
let tracks = try await asset.loadTracks(withMediaType: .video)
var streams: [[String:Any]] = []
for track in tracks {
    let size = try await track.load(.naturalSize)
    let transform = try await track.load(.preferredTransform)
    let bounds = CGRect(origin: .zero, size: size).applying(transform)
    let descriptions = try await track.load(.formatDescriptions)
    let subtype = CMFormatDescriptionGetMediaSubType(descriptions[0])
    let code = String(bytes: [UInt8((subtype >> 24) & 255), UInt8((subtype >> 16) & 255), UInt8((subtype >> 8) & 255), UInt8(subtype & 255)], encoding: .ascii) ?? "unknown"
    streams.append(["codec_type":"video", "codec_name": ["avc1","avc3"].contains(code) ? "h264" : code, "width":Int(abs(bounds.width).rounded()), "height":Int(abs(bounds.height).rounded())])
}
let playable = try await asset.load(.isPlayable)
let metadata: [String:Any] = ["streams":streams,"format":["duration":CMTimeGetSeconds(duration)],"playable":playable]
print(String(data: try JSONSerialization.data(withJSONObject: metadata, options: [.sortedKeys]), encoding: .utf8)!)
