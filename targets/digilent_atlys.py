# Support for the Digilent Atlys board - digilentinc.com/atlys/

from fractions import Fraction

from migen.fhdl.std import *
from migen.genlib.resetsync import AsyncResetSynchronizer

from misoclib.mem.sdram.module import SDRAMModule
from misoclib.mem.sdram.phy import s6ddrphy
from misoclib.mem.sdram.core.lasmicon import LASMIconSettings
from misoclib.mem.flash import spiflash
from misoclib.soc import mem_decoder
from misoclib.soc.sdram import SDRAMSoC

from misoclib.com.liteeth.phy import LiteEthPHY
from misoclib.com.liteeth.core.mac import LiteEthMAC


class P3R1GE3EGF(SDRAMModule):
    # MIRA P3R1GE3EGF
    # Density: 1G bits
    # 8M words × 16 bits × 8 banks (P3R1GE4JGF) -- 1235E - G8E -- E20316JOR826
    # 2KB page size (P3R1GE4JGF) - Row address: A0 to A12 - Column address: A0 to A9
    # http://208.74.204.60/t5/Spartan-Family-FPGAs/Atlys-DDR2-memory/td-p/497304
    geom_settings = {
        "nbanks": 8,
        "nrows": 8192,
        "ncols": 1024,
        # bank_a=3,
        # row_a=12, # Note: 1. A13 pin is NC for × 16 organization.
        # col_a=10,
    }
    timing_settings = {
        "tRP":  15, # 12.5 ns  (MIG 15ns)
        "tRCD": 15, # 12.5 ns  (MIG 15ns)
        "tWR":  15, # 15.0 ns  (MIG 15ns)
        "tWTR":  2, # 7.5 ns   (MIG same)
        "tREFI": 7800,  # 7.8 uS
        "tRFC":  127.5, # 256Mb = 75ns, 512Mb = 105ns, 1Gb = 127.5ns, 2Gb = 197.5ns
        #req_queue_size=8,
        #read_time=32,
        #write_time=16
    }

    def __init__(self, clk_freq):
        SDRAMModule.__init__(self, clk_freq, "DDR2", self.geom_settings,
            self.timing_settings)


class _CRG(Module):
    def __init__(self, platform, clk_freq):
        self.clock_domains.cd_sys = ClockDomain()
        self.clock_domains.cd_sdram_half = ClockDomain()
        self.clock_domains.cd_sdram_full_wr = ClockDomain()
        self.clock_domains.cd_sdram_full_rd = ClockDomain()

        self.clk4x_wr_strb = Signal()
        self.clk4x_rd_strb = Signal()

        f0 = 100*1000000
        clk100 = platform.request("clk100")
        clk100a = Signal()
        self.specials += Instance("IBUFG", i_I=clk100, o_O=clk100a)
        clk100b = Signal()
        self.specials += Instance("BUFIO2", p_DIVIDE=1,
                                  p_DIVIDE_BYPASS="TRUE", p_I_INVERT="FALSE",
                                  i_I=clk100a, o_DIVCLK=clk100b)
        f = Fraction(int(clk_freq), int(f0))
        n, m = f.denominator, f.numerator
        assert f0/n*m == clk_freq
        p = 8
        pll_lckd = Signal()
        pll_fb = Signal()
        pll = Signal(6)
        self.specials.pll = Instance("PLL_ADV", p_SIM_DEVICE="SPARTAN6",
                                     p_BANDWIDTH="OPTIMIZED", p_COMPENSATION="INTERNAL",
                                     p_REF_JITTER=.01, p_CLK_FEEDBACK="CLKFBOUT",
                                     i_DADDR=0, i_DCLK=0, i_DEN=0, i_DI=0, i_DWE=0, i_RST=0, i_REL=0,
                                     p_DIVCLK_DIVIDE=1, p_CLKFBOUT_MULT=m*p//n, p_CLKFBOUT_PHASE=0.,
                                     i_CLKIN1=clk100b, i_CLKIN2=0, i_CLKINSEL=1,
                                     p_CLKIN1_PERIOD=1000000000/f0, p_CLKIN2_PERIOD=0.,
                                     i_CLKFBIN=pll_fb, o_CLKFBOUT=pll_fb, o_LOCKED=pll_lckd,
                                     o_CLKOUT0=pll[0], p_CLKOUT0_DUTY_CYCLE=.5,
                                     o_CLKOUT1=pll[1], p_CLKOUT1_DUTY_CYCLE=.5,
                                     o_CLKOUT2=pll[2], p_CLKOUT2_DUTY_CYCLE=.5,
                                     o_CLKOUT3=pll[3], p_CLKOUT3_DUTY_CYCLE=.5,
                                     o_CLKOUT4=pll[4], p_CLKOUT4_DUTY_CYCLE=.5,
                                     o_CLKOUT5=pll[5], p_CLKOUT5_DUTY_CYCLE=.5,
                                     p_CLKOUT0_PHASE=0., p_CLKOUT0_DIVIDE=p//4,  # sdram wr rd
                                     p_CLKOUT1_PHASE=0., p_CLKOUT1_DIVIDE=p//8,
                                     p_CLKOUT2_PHASE=270., p_CLKOUT2_DIVIDE=p//2,  # sdram dqs adr ctrl
                                     p_CLKOUT3_PHASE=250., p_CLKOUT3_DIVIDE=p//2,  # off-chip ddr
                                     p_CLKOUT4_PHASE=0., p_CLKOUT4_DIVIDE=p//1,
                                     p_CLKOUT5_PHASE=0., p_CLKOUT5_DIVIDE=p//1,  # sys
        )
        self.specials += Instance("BUFG", i_I=pll[5], o_O=self.cd_sys.clk)
        reset = platform.request("cpu_reset")
        self.clock_domains.cd_por = ClockDomain()
        por = Signal(max=1 << 11, reset=(1 << 11) - 1)
        self.sync.por += If(por != 0, por.eq(por - 1))
        self.comb += self.cd_por.clk.eq(self.cd_sys.clk)
        self.specials += AsyncResetSynchronizer(self.cd_por, reset)
        self.specials += AsyncResetSynchronizer(self.cd_sys, ~pll_lckd | (por > 0))
        self.specials += Instance("BUFG", i_I=pll[2], o_O=self.cd_sdram_half.clk)
        self.specials += Instance("BUFPLL", p_DIVIDE=4,
                                  i_PLLIN=pll[0], i_GCLK=self.cd_sys.clk,
                                  i_LOCKED=pll_lckd, o_IOCLK=self.cd_sdram_full_wr.clk,
                                  o_SERDESSTROBE=self.clk4x_wr_strb)
        self.comb += [
            self.cd_sdram_full_rd.clk.eq(self.cd_sdram_full_wr.clk),
            self.clk4x_rd_strb.eq(self.clk4x_wr_strb),
        ]
        clk_sdram_half_shifted = Signal()
        self.specials += Instance("BUFG", i_I=pll[3], o_O=clk_sdram_half_shifted)

        output_clk = Signal()
        clk = platform.request("ddram_clock")
        self.specials += Instance("ODDR2", p_DDR_ALIGNMENT="NONE",
                                  p_INIT=0, p_SRTYPE="SYNC",
                                  i_D0=1, i_D1=0, i_S=0, i_R=0, i_CE=1,
                                  i_C0=clk_sdram_half_shifted, i_C1=~clk_sdram_half_shifted,
                                  o_Q=output_clk)
        self.specials += Instance("OBUFDS", i_I=output_clk, o_O=clk.p, o_OB=clk.n)


class BaseSoC(SDRAMSoC):
    default_platform = "digilent_atlys"

    csr_map = {
        "spiflash": 16,
        "ddrphy":   17,
    }
    csr_map.update(SDRAMSoC.csr_map)

    def __init__(self, platform, sdram_controller_settings=LASMIconSettings(), **kwargs):
        clk_freq = 80*1000000
        SDRAMSoC.__init__(self, platform, clk_freq,
                          integrated_rom_size=0x8000,
                          sdram_controller_settings=sdram_controller_settings,
                          **kwargs)

        self.submodules.crg = _CRG(platform, clk_freq)

        if not self.integrated_main_ram_size:
            self.submodules.ddrphy = s6ddrphy.S6DDRPHY(platform.request("ddram"),
                                                       P3R1GE3EGF(self.clk_freq),
                                                       rd_bitslip=1,
                                                       wr_bitslip=3,
                                                       dqs_ddr_alignment="C1")
            self.comb += [
                self.ddrphy.clk4x_wr_strb.eq(self.crg.clk4x_wr_strb),
                self.ddrphy.clk4x_rd_strb.eq(self.crg.clk4x_rd_strb),
            ]
            self.register_sdram_phy(self.ddrphy)

default_subtarget = BaseSoC


class MiniSoC(BaseSoC):
    csr_map = {
        "ethphy": 18,
        "ethmac": 19,
    }
    csr_map.update(BaseSoC.csr_map)

    interrupt_map = {
        "ethmac": 2,
    }
    interrupt_map.update(BaseSoC.interrupt_map)

    mem_map = {
        "ethmac": 0x30000000,  # (shadow @0xb0000000)
    }
    mem_map.update(BaseSoC.mem_map)

    def __init__(self, platform, **kwargs):
        BaseSoC.__init__(self, platform, **kwargs)

        self.submodules.ethphy = LiteEthPHY(platform.request("eth_clocks"), platform.request("eth"))
        self.submodules.ethmac = LiteEthMAC(phy=self.ethphy, dw=32, interface="wishbone")
        self.add_wb_slave(mem_decoder(self.mem_map["ethmac"]), self.ethmac.bus)
        self.add_memory_region("ethmac", self.mem_map["ethmac"]+self.shadow_address, 0x2000)

default_subtarget = BaseSoC
