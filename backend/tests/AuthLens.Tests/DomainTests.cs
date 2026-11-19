using AuthLens.Domain.Csv;
using AuthLens.Domain.Roles;
using AuthLens.Domain.Text;

namespace AuthLens.Tests;

/// <summary>Spot checks of ported rules; broad behaviour is proven against Python v1 by the equivalence harness (tools/compare_equivalence.py).</summary>
public sealed class DomainTests
{
    [Theory]
    [InlineData(" zc:fi :role 1 ", "ZC:FI:ROLE1")]
    [InlineData("zo:mm\u001f:x", "ZO:MM:X")]
    public void Role_names_are_normalized_like_v1(string raw, string expected) => Assert.Equal(expected, RoleNames.Normalize(raw));

    [Fact]
    public void Release_roles_are_parsed()
    {
        var r = RoleNames.ParseRelease("ZO:MM:M0:PO_REL_ST_E0_00:ALL");
        Assert.True(r.Parsed);
        Assert.Equal("PO", r.DocumentType);
    }

    [Fact]
    public void Matcher_resolves_exact_wildcard_and_unmapped()
    {
        var m = new RoleMatcher(["ZC:FI:A", "ZC:FI:*", "ZC:CO:A", "zc:co:a "]);
        Assert.Equal("exact", m.Match("zc:fi:a").Status);
        Assert.Equal("wildcard", m.Match("ZC:FI:B").Status);
        Assert.Equal("ambiguous", m.Match("ZC:CO:A").Status);
        Assert.Equal("unmapped", m.Match("ZC:HR:A").Status);
    }

    [Fact]
    public void Text_patterns_are_anchored()
    {
        Assert.True(TextMatching.TextMatches("ME21N", "ME2*"));
        Assert.False(TextMatching.TextMatches("ME21N", "E2*"));
    }

    [Theory]
    [InlineData("a;b;c\n1;2;3\n4;5;6\n", ';')]
    [InlineData("a,b,c\n1,2,3\n4,5,6\n", ',')]
    [InlineData("a\tb\n1\t2\n", '\t')]
    public void Delimiter_is_sniffed_like_cpython(string sample, char expected) => Assert.Equal(expected, PythonSniffer.Sniff(sample, ",;\t|"));
}
