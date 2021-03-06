from migen.fhdl.std import ClockSignal

from gateware.hdmi_in import HDMIIn

from gateware.hdmi_out import HDMIOut

from targets.common import *
from targets.opsis_base import default_subtarget as BaseSoC


def CreateVideoMixerSoC(base):

    class CustomVideoMixerSoC(base):
        csr_peripherals = (
            "hdmi_out0",
            "hdmi_out1",
            "hdmi_in0",
            "hdmi_in0_edid_mem",
            "hdmi_in1",
            "hdmi_in1_edid_mem",
        )
        csr_map_update(base.csr_map, csr_peripherals)
    
        interrupt_map = {
            "hdmi_in0": 3,
            "hdmi_in1": 4,
        }
        interrupt_map.update(base.interrupt_map)
    
        def __init__(self, platform, **kwargs):
            base.__init__(self, platform, **kwargs)

            self.submodules.hdmi_in0 = HDMIIn(
                platform.request("hdmi_in", 0),
                self.sdram.crossbar.get_master(),
                fifo_depth=512,
                soc=self)
            self.submodules.hdmi_in1 = HDMIIn(
                platform.request("hdmi_in", 1),
                self.sdram.crossbar.get_master(),
                fifo_depth=512,
                soc=self)

            self.submodules.hdmi_out0 = HDMIOut(
                platform.request("hdmi_out", 0),
                self.sdram.crossbar.get_master(),
                clock50=ClockSignal(self.crg.cd_periph.name),
                fifo_depth=1024)
            # Share clocking with hdmi_out0 since no PLL_ADV left.
            self.submodules.hdmi_out1 = HDMIOut(
                platform.request("hdmi_out", 1),
                self.sdram.crossbar.get_master(),
                external_clocking=self.hdmi_out0.driver.clocking,
                fifo_depth=1024)

            # all PLL_ADV are used: router needs help...
            platform.add_platform_command("""INST PLL_ADV LOC=PLL_ADV_X0Y0;""")
            # FIXME: Fix the HDMI out so this can be removed.
            platform.add_platform_command(
                """PIN "hdmi_out_pix_bufg.O" CLOCK_DEDICATED_ROUTE = FALSE;""")
            platform.add_platform_command(
                """PIN "hdmi_out_pix_bufg_1.O" CLOCK_DEDICATED_ROUTE = FALSE;""")
            # We have CDC to go from sys_clk to pixel domain
            platform.add_platform_command(
                """
# Separate TMNs for FROM:TO TIG constraints
NET "{pix0_clk}" TNM_NET = "TIGpix0_clk";
NET "{pix1_clk}" TNM_NET = "TIGpix1_clk";
TIMESPEC "TSpix0_to_sys" = FROM "TIGpix0_clk" TO "TIGsys_clk"  TIG;
TIMESPEC "TSsys_to_pix0" = FROM "TIGsys_clk"  TO "TIGpix0_clk" TIG;
TIMESPEC "TSpix1_to_sys" = FROM "TIGpix1_clk" TO "TIGsys_clk"  TIG;
TIMESPEC "TSsys_to_pix1" = FROM "TIGsys_clk"  TO "TIGpix1_clk" TIG;
""",
                pix0_clk=self.hdmi_out0.driver.clocking.cd_pix.clk,
                pix1_clk=self.hdmi_out1.driver.clocking.cd_pix.clk,
            )

            for k, v in sorted(platform.hdmi_infos.items()):
                self.add_constant(k, v)

    return CustomVideoMixerSoC


VideoMixerSoC = CreateVideoMixerSoC(BaseSoC)
default_subtarget = VideoMixerSoC
