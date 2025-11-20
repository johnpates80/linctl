class Linctl < Formula
  desc "Comprehensive command-line interface for Linear's API"
  homepage "https://github.com/raegislabs/linctl"
  url "https://github.com/raegislabs/linctl/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "7aea99cc1bee2f097020930e0cc9e7a575340ab4969e81d673299a60ad586874"
  license "MIT"
  head "https://github.com/raegislabs/linctl.git", branch: "master"

  depends_on "go" => :build

  def install
    system "go", "build", *std_go_args(ldflags: "-s -w -X github.com/raegislabs/linctl/cmd.version=#{version}")
  end

  test do
    # Test version output
    assert_match "linctl version #{version}", shell_output("#{bin}/linctl --version")
    
    # Test help command
    assert_match "A comprehensive CLI tool for Linear", shell_output("#{bin}/linctl --help")
  end
end
