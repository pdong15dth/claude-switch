import AppKit
import Foundation

let outputDirectory = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : "."
let size: CGFloat = 1024

let image = NSImage(size: NSSize(width: size, height: size))
image.lockFocus()

let background = NSColor(srgbRed: 0.941, green: 0.933, blue: 0.902, alpha: 1)
background.setFill()
NSBezierPath(
    roundedRect: NSRect(x: 0, y: 0, width: size, height: size),
    xRadius: 224,
    yRadius: 224
).fill()

let ink = NSColor(srgbRed: 0.851, green: 0.467, blue: 0.341, alpha: 1)
ink.setStroke()

let center = NSPoint(x: size / 2, y: size / 2)
let rayCount = 12
let outer: CGFloat = 392
let inner: CGFloat = 68
let lengths: [CGFloat] = [
    1.0, 0.90, 0.97, 0.86, 0.95, 0.90,
    1.0, 0.88, 0.96, 0.90, 0.98, 0.87,
]

let path = NSBezierPath()
path.lineWidth = 58
path.lineCapStyle = .round
for index in 0..<rayCount {
    let angle = CGFloat(index) / CGFloat(rayCount) * .pi * 2 + .pi / 12
    let length = outer * lengths[index]
    path.move(to: NSPoint(x: center.x + cos(angle) * inner, y: center.y + sin(angle) * inner))
    path.line(to: NSPoint(x: center.x + cos(angle) * length, y: center.y + sin(angle) * length))
}
path.stroke()

image.unlockFocus()

guard
    let tiff = image.tiffRepresentation,
    let bitmap = NSBitmapImageRep(data: tiff),
    let png = bitmap.representation(using: .png, properties: [:])
else {
    FileHandle.standardError.write(Data("icon rendering failed\n".utf8))
    exit(1)
}

let url = URL(fileURLWithPath: outputDirectory).appendingPathComponent("icon_1024.png")
do {
    try png.write(to: url)
} catch {
    FileHandle.standardError.write(Data("cannot write icon: \(error)\n".utf8))
    exit(1)
}
