## Practical guidelines for DFIT interpretation using the ‘compliance method’ procedure from URTeC-2019-123

Mark McClure<sup>1</sup>, Dave Ratcliff<sup>1</sup>, Ankush Singh<sup>1</sup>, Chris Ponners<sup>1</sup>, and Garrett Fowler<sup>1</sup>

<sup>1</sup>ResFrac Corporation

[email protected]

https://eartharxiv.org/repository/view/7828/

## Introduction

This blog post provides practical tips for interpreting Diagnostic Fracture Injection Tests (DFITs) using the ‘compliance method’ procedure initially developed by McClure et al. (2016) and refined in the paper URTeC-2019-123, which summarized results from a joint industry study performed with a consortium of operators (McClure et al., 2019).

The results from McClure et al. (2016) demonstrated that common practices for stress estimation often underestimate the true magnitude of the minimum principal stress, a finding that has been subsequently been confirmed by direct in-situ measurements and laboratory experiments (Dutler et al., 2020; Bröker and Ma, 2022; Guglielmi et al., 2023; Ye and Ghassemi et al., 2023), as well as in the field measurements reviewed by McClure et al. (2016).

URTeC-2019-123 provides a step-by-step process for estimating stress, permeability, and pore pressure. It also discusses how to handle topics such as near-wellbore tortuosity and deviation from Carter leakoff. However, the paper primarily focuses on interpreting ‘ideal’ data – tests that conform to the behavior seen in ‘typical’ DFIT numerical simulations. McClure et al. (2022) performed a statistical review of 62 field DFITs from around North America and observed significant deviation from ideality in many of the tests. For example, an “S” shaped dP/dG curve, which is used for estimating stress, is not seen in a significant percentage of DFITs.

For practical purposes, we need guidelines for interpreting DFITs when ideal conditions are not met. This document provides recommendations based on the authors’ experience analyzing a large number of DFITs across North and South America.

Among commercial codes, the procedure from URTeC-2019-123 is now available in Kappa’s Saphir. Also, it will be available in Whitson’s under-development DFIT tool.

Finally, please check out the DFIT seminar I gave at Whitson earlier this month.

## The primary interpretation procedure

The full interpretation procedure is summarized in Section 2.2 from URTeC-2019-123. A practical/simplified version of the procedure is provided below.

1. Generate a Cartesian plot of the data and pick the ‘start of injection’ and the ‘shut-in time.’
2. Smooth the pressure data by resampling along pressure increments, usually 30 psi. If needed, calculate BHP from WHP, taking care to use an accurate fluid density (accounting for dissolved solids).
3. Construct diagnostic plots of the data: pressure and dP/dG versus G-time, and the log-log derivative plot. On the log-log plot, the derivative should be taken with respect to actual shut-in time, not a transformation of time such as ‘superposition time.’
4. Estimate the magnitude of Shmin and the effective ISIP from the G-function plot. Stress is estimated from the ‘compliance method’ procedure based on the dP/dG curve, as described in Section 3.1.2 of URTeC-2019-123.
5. From the log-log plot, interpret the late-time impulse linear and/or radial flow regimes.
6. Based on the log-log interpretation, use a plot of either pressure versus t<sup>-1/2</sup> or t<sup>-1</sup> to estimate pore pressure.
7. Estimate permeability using: (a) impulse linear or (very seldom) radial, if available; (b) the h-function method (dividing by 1.5x to account for bias, as discussed by McClure et al., 2022); and (c) if the data prevents methods (a) or (b) from being possible, using the G-function method (dividing by 2x to account for bias, as discussed by McClure et al., 2022).

## Handling practical issues and special cases

The sections below address practical issues and ‘gotchas’ that often come up during interpretation.

#### Importing data

We are often not provided rate data. If we do have rate data, sometimes it is not correctly sync’ed up in time with the pressure data. Thus, it is critical to plot the pressure data and visually confirm the start and end of injection.

Sometimes prior to the DFIT, there are a few cycles where they pressure up the well, hold, and then bleed off. Don’t count these pretest cycles as the start of the DFIT.

At the end of injection, look for a point when pressure suddenly drops off. Sometimes, there is a step-down test at the end, where rate is decreased over a series of steps. Make sure to pick the final sudden drop in pressure as shut-in. Otherwise, you may pick the end of injection at the first rate drop in the step down, which rate has not yet reached zero.

To construct the G-function, you need to define t<sub>e</sub>, which is the ‘duration of injection.’ Don’t use the actual, literal duration of injection. Instead, take the total volume of injected and divide by the maximum sustained injection rate.

There are two commonly-used expressions for G-time. Unless in very high permeability rock (&gt;1 md), use the expression for ‘alpha = 1’, which is the form that uses powers of 1.5. In high permeability rock, use the expression for ‘alpha = 0.5’, which is the form that uses arcsin.

#### Smoothing the data

Pressure measurements are usually provided with 1 second resolution. This resolution is too fine to derive accurate numerical derivatives and generally, it is inconvenient to work with (the data routinely exceeds 1 million rows).

We recommend performing pressure resampling at increments of 20-30 psi. This smooths the data, sparsens into a manageable number of rows, and facilitates the calculation of numerical derivatives from adjacent rows in the table.

#### Setting up formation properties

The permeability estimate requires estimates for porosity, viscosity, compressibility, Young’s modulus, and Poisson’s ratio. This information must be available from data available independent from the DFIT (such as core, log measurements, and fluid samples).

The most common mistake is to use the wrong viscosity or compressibility. If interpreting a test from a gas reservoir, the viscosity should be in the ballpark of .03 cp, and the compressibility should be in the ballpark of 2e-4 psi<sup>-1</sup>. In an oil reservoir, in shale, the viscosity is usually in the vicinity of 0.3 cp, and the compressibility is in the vicinity of 1e-5 psi<sup>-1</sup>.

#### Plotting dP/dG

The primary derivative dP/dG usually starts very high and drops off rapidly. The contact point is picked from the upward deflection in dP/dG after the initial dropoff. When the computer automatically selects an axis scale for dP/dG, it will select a high value for the maximum, so that it can bound the large initial values of dP/dG. This is problematic because the high axis value makes it difficult to see the upward deflection, which happens later, and involves lower values of dP/dG. Thus, it is necessary to manually adjust the axis scale for dP/dG so that it is sufficiently low to visualize the shape of the curve after the initial falloff.

For example, in Figs 1 and 2 below, the initial high values of dP/dG to the upper left are not visible on the plot. The axis scale has been manually decreased so that we can see the character of the curve during the ‘contact’ deflections that occur around G = 20.

#### Estimating the magnitude of the minimum principal stress

The plots below illustrate different trends that may be observed in G-function plots.

##### Scenario C-A: Clear contact point

In this scenario, the dP/dG makes a clear “S” shape. This is the ‘ideal’ trend that we see roughly half of field DFITs, and which is easily reproduced in numerical simulations. The early-time pressure drop is related to near-wellbore tortuosity. The derivative decreases as the ‘near-wellbore tortuosity’ effect dissipates. Then, the derivative increases when the fracture walls contact because the system becomes stiffer. The ‘contact pressure’ should be picked once dP/dG increases roughly 10% from the minimum point. Then, subtract 75 psi to account for crack roughness at contact, and the result is the ‘best estimate’ for Shmin.

You should not use the ‘holistic method’ concepts of ‘tip-extension,’ ‘pressure-dependent leakoff,’ ‘fracture height recession,’ or ‘transverse storage.’ While these things could hypothetically occur, G-function the plotting techniques used to ‘diagnose’ these phenomena are flawed and usually lead to misinterpretation. These G-function plot interpretations were developed from unrealistic numerical simulation approaches that oversimplify the physics of closure.

In the plot below, the contact pressure should be picked at roughly 21 G-time. Then, Shmin is estimated as pressure at that point in time minus 75 psi (slightly below 9500 psi).

The effective ISIP is estimated by extrapolating a straight line from the pressure versus G-time plot back to the y-intercept at G = 0, starting from the point of minimum dP/dG (ie, at G-time of roughly 18 in the example below). In the test below, the effective ISIP is roughly 9800 psi.

Figure 1: Example of Scenario C-A: Clear contact point

##### Scenario C-B: Adequate contact point

In these tests, dP/dG monotonically decreases, instead of showing a clear “S” shape with a min/max. However, stress can still be estimated with ‘adequate’ confidence if there is an inflection point in dP/dG. For example, in the plot below, dP/dG is curving upwards until roughly 22 G-time, and then curves downward. This inflection point at 22 G-time can be used as an estimate for the contact point. As with the standard pick, the stress estimate should be the pressure at the contact point minus 75 psi.

Figure 2: Example of Scenario C-B: Adequate contact point

The plot below in Figure 3 shows a more difficult example. Again, dP/dG reaches a slight minimum and then inflects slightly upwards. But subsequently, the dP/dG curve mostly flattens, rather than bending back down. The stress estimate in this test is less confident than in the prior example. Nevertheless, it is acceptable to pick the contact point –at around G-time of 24.

Net pressure is seldom going to be much greater than 500 psi. Thus, if the shape of the dP/dG curve flattens sufficiently that we can make a reasonable pick for effective ISIP, then as long as the stress estimate is within 500 psi or so of the effective ISIP, we can’t be too off. In this case, the effective ISIP estimate is roughly 5700 psi, about 500 greater than the stress estimate.

Figure 3: Example of Scenario C-B: Adequate contact point

##### Scenario C-C: No contact point

In some tests, we cannot estimate identify a compliance-method contact point and make a stress estimate. This occurs in tests where not only is dP/dG continuously decreasing, but also, dP/dG does not have an inflection point. For example, in the test below, dP/dG is continuously decreasing and continuously bending upwards. In this test, we must decline to estimate stress from the test.

Without estimates for stress and effective ISIP, we are also unable to estimate permeability. However, it is still possible to estimate pore pressure from these tests.

Figure 4: Example of Scenario C-C: No contact point

##### Scenario C-D: Rapid closure

This is a special case when it is possible to estimate stress, even though dP/dG is monotonically decreasing and continuously concave up. If you feel it is appropriate to assume that there is not any near-wellbore tortuosity, then you may interpret these tests as ‘rapid closure.’ This could happen, for example, if the well is vertical and so the fracture is initiating longitudinally along the well.

Monotonic dP/dG occurs because the fracture closes shortly after shut-in (because of rapid leakoff into the matrix or preexisting fractures). In this case, the best interpretation is that the fracture is closing rapidly, and the stress estimate is within several hundred psi of the ISIP. As discussed in URTeC-2019-123, monotonic dP/dG develops from rapid closure because the fracture remains effectively ‘finite conductivity’ through closure because of the (relatively) rapid progression of the transient. The upward deflection in dP/dG caused by the increase in stiffness is masked by the pressure transient that has developed along the fracture itself.

The stress estimate is fairly uncertain, within several hundred psi of the ISIP, and so in this case, we cannot estimate the ‘net pressure’ (ISIP – Shmin). Therefore, even though we have a stress estimate, we don’t have a confident estimate of fracture size and so cannot estimate permeability.

The figure below shows a DFIT that was performed at very low rate from a prenotched wellbore at the EGS Collab project (described by Guglielmi et al., 2023). In this case, the interpretation is somewhat ambiguous. If this well was not prenotched (to create initiation points), we might be tempted to estimate Shmin around 2300-2400 psi and effective ISIP around 2900 psi. However, because we believe that there should not be wellbore tortuosity, we may instead suspect ‘rapid closure’ and estimate stress in the vicinity of 3000-3400 psi.

Figure 5: Example of Scenario C-D: Rapid closure

In this dataset, a specialized downhole tool was used to make direct strain measurements during closure. These measurements provide an independent measurement of Shmin. Also, there was another fracture/shut-in test performed immediately prior, which showed minimal evidence of near-wellbore tortuosity and had a clear pick for the contact point. Both the prior test and the strain measurements indicate that stress is 3100 psi, supporting the ‘rapid closure’ interpretation.

Figures 13 and 14 from Malik et al. (2014) provide another example. These figures show repeated injection/shut-in tests performed by a formation tester tool along a vertical openhole wellbore. Their Figure 13 shows that the reopening pressure is close to the ISIP. Because their tests are from a vertical open wellbore, the reopening pressure can be taken as good estimates for Shmin. Their Figure 14 shows ‘tangent method’ stress interpretations of the shut-in data, which is yield stress estimates 100s of psi lower than the observed reopening pressures. The dP/dG curves are monotonically decreasing with continuous upward curvature, consistent with the ‘rapid closure’ interpretation, and consistent with the reopening pressures.

The ‘rapid closure’ interpretation should be considered in the context of the injection volume/rate and formation permeability. If you are performing an injection/falloff test in a vertical well with permeability of 100 md, you can be certain that the pressure will fall off very rapidly after shut-in, and a ‘rapid closure’ interpretation will be appropriate.

Injection volume and rate also affect the probability of a ‘rapid closure’. Field-scale DFITs are injected at 1-10 bpm. But ‘microfrac’ tests may be pumped liters per minute, or even, 100s of mL per minute, 100-1000x lower than a field scale DFIT. With such low injection rate and volume, fracture aperture is tiny, and even very low permeability may be sufficient to cause ‘rapid closure.’ Consistent with this intuition, we observe that ‘rapid closure’ is the most common observation in microfrac tests.

To reiterate – if tests are performed in horizontal or significantly deviated wells, there is a significant risk that near-wellbore tortuosity will overprint on the observed signal. In situations with both high permeability and large expected near-wellbore tortuosity, it is doubtful whether a confident stress estimate can be obtained.

#### Diagnose postclosure behavior

Use the log-log plot to diagnose the postclosure behavior. This interpretation helps you decide: (a) how to estimate permeability, and (b) how to estimate pore pressure. Note that in all cases, the derivatives are taken with respect to actual shut-in time, rather than ‘superposition time.’ As discussed by McClure (2017), the ‘superposition time derivative’ is not recommended for DFIT interpretation.

##### Scenario PC-A: Postclosure linear flow

The figure below shows the ‘ideal’ DFIT postclosure transient. The log-log derivative plot peaks and then bends down into a -1/2 slope, corresponding to postclosure linear flow. On the plot, the red line does not visually appear to have a -1/2 slope, but this is an artifact because the y-axis is stretched relative to the x-axis.

The -1/2 slope occurs because pressure change is scaling with shut-in time to the -1/2 power. A -1 slope would indicate that pressure change is scaling with shut-in time to the -1 power.

Figure 6: Example of Scenario PC-A: Postclosure linear flow. The dashed black line has a slope of -1/2.

##### Scenario PC-B: False radial

False radial is very common in formations where the reservoir fluid is gas or high-GOR volatile oil. It is characterized by an immediate bend into a -1 slope after the peak in the derivative. This is not genuine radial flow geometry and should not be used to estimate permeability. However, it is possible to get a reasonably accurate estimate for pore pressure.

Figure 7: Example of Scenario PC-B: False radial. The green line has a slope of -1.

##### Scenario PC-C: False radial into genuine linear

If the transient duration is sufficiently long (or false radial occurs sufficiently early), then the transient can slip into a -1/2 slope after the false radial signature. This is uncommon because shut-in usually ends too early for the test to reach genuine linear flow after false radial. A reminder – false radial only occurs in gas reservoirs or high GOR volatile oils.

With this scenario, the later -1/2 slope can be interpreted as genuine linear and used to estimate both permeability and pore pressure.

Figure 8: Example of Scenario PC-C: False radial into genuine linear. The green line has a slope of -1. The dashed black line has a slope of -1/2.

##### Scenario PC-D: Genuine linear to genuine radial

In the test below, there is an extended -1/2 slope after the peak, followed by a -1 slope. The -1 slope can be interpreted as genuine radial. This is not common, because in most tests, the shut-in duration would need to be weeks or months until the test reached genuine radial. In the test below (which was performed in an oil shale), the permeability was relatively high for a shale (tens of microdarcy), the injection volume was unusually low (less than 10 bbl), and the shut-in was unusually long (several weeks). This combination of factors made it possible to achieve genuine radial prior to the end of the test.

In this scenario, either the linear or radial periods can be used to estimate permeability and pore pressure. As a QC, the estimates can be compared, and they should be similar. In the test shown below, as expected, the radial and linear permeability estimates were similar.

Figure 9: Example of Scenario PC-D: Genuine linear to genuine radial. The dashed black line has a slope of -1/2. The green line has a slope of -1.

##### Scenario PC-E: Derivative reaches a peak but the postclosure trend is not established

In the test below, the derivative plot reaches a peak but does not progress for sufficient duration to establish a clear -1/2 slope. With ‘adequate’ confidence, it is acceptable to extrapolate the remaining data on a t<sup>1/2</sup> trend to estimate pore pressure. This yields an acceptable, but somewhat uncertain, pore pressure estimate.

This scenario is fairly common in practical DFITs, even with the standard one-week shut-in. Larger injection volumes tend to delay the onset of impulse linear flow, which is one reason why we recommend using relatively small (10-20 bbl) injection volumes.

Figure 10: Example of Scenario PC-E: Derivative reaches a peak but the postclosure trend is not established.

##### Scenario PC-F: The derivative does not reach a peak

In the test below, the derivative curve is still increasing at the end of the test. It is not possible to estimate pore pressure from this test. Because pore pressure cannot be estimated, it is also not possible to estimate permeability.

Figure 11: Example of Scenario PC-F: The derivative does not reach a peak.

## Based on closure and postclosure interpretation, apply an appropriate procedure for estimating stress, pore pressure, permeability

The procedure for estimating pore pressure and/or permeability depends on the interpretations that have been made on the data. The first two columns of the table below categorize different combinations of ‘closure interpretation’ and ‘postclosure interpretation,’ based on the scenarios listed in the sections above. Columns 3-5 from the table below specify how to estimate stress, pore pressure, and permeability for each combination of scenarios. These recommendations follow the procedures from URTeC-2019-123 (McClure et al., 2019) and McClure et al. (2022).

#### Stress estimate

If the procedure says to use the ‘minimum in dP/dG,’ then identify the contact pressure once dP/dG has risen about 10% from the minimum, and then subtract 75 psi. To estimate effective ISIP, draw a straight line through the pressure versus G-time curve (starting from the point of minimum dP/dG) and pick the y-intercept (Section 3.1.1 from McClure et al., 2019).

If the procedure says to use the ‘inflection point in dP/dG’, identify the contact pressure shortly after the inflection point of dP/dG (where the slope stops curving upwards and starts curving downwards). Subtract 75 psi for the stress estimate. To estimate effective ISIP, draw a straight line through the pressure versus G-time curve (starting from the injection point in dP/dG) and pick the y-intercept.

If the procedure says ‘within a few 100 psi of the ISIP’, then estimate the literal ISIP by plotting pressure versus G-time after shut-in, and pick ISIP at the deviation from the straight line. Then, subtract a few hundred psi (100-250 psi are reasonable values) and use this as an approximate range for Shmin.

If the procedure says ‘none’, then it is not possible to estimate the minimum principal stress from the test.

#### Pore pressure estimate

If the procedure says to ‘extrapolate t<sup>-1/2</sup>’, then make a plot of pressure versus shut-in time to the -1/2 power and draw a straight line through the end of the data to the y-axis (corresponding to time infinity) (Section 3.1.6 from McClure et al., 2019).

If the procedure says to ‘extrapolate t<sup>-1/2</sup> from peak’, then make a plot of pressure versus shut-in time to the -1/2 power and draw a straight line from the final point in the data to the y-axis (corresponding to time infinity).

Figure 12: Example of extrapolating a linear flow period to reciprocal sqrt(t) of zero to estimate pore pressure. Note that this figure is plotting WHP, and so the values would need to be appropriately adjusted for hydrostatic to estimate BHP in the target interval.

If the procedures says to ‘extrapolate t<sup>-1</sup>’, then make a plot of pressure versus shut-in time to the -1 power and draw a straight line through the end of the data to the y-axis (corresponding to time infinity).

If the procedure says ‘none’, then it is not possible to estimate the pore pressure from the test.

#### Permeability estimate

If the procedure says ‘postclosure linear’, then use the method in Section A.10.iii from URTeC-2019-123.

If the procedure says ‘h-function divided by 1.5’, then use the method in Section A.10.ii from URTeC-2019-123, and then divide by 1.5. The result is divided by 1.5 because empirical comparison suggests that permeability estimates tend to be about 1.5x higher than postclosure linear estimates, and the latter are considered to be more accurate (page 18 from SPE-205297).

If the procedure says ‘postclosure radial’, then use the method in Section A.10.iv from URTeC-2019-123.

If the procedure says ‘none’, then it is not possible to estimate the permeability from the test.

The test measures the effective permeability to the mobile reservoir fluid. So for example, if the mobile reservoir fluid is oil, then the test is measuring k*kr, the product of absolute permeability and relative permeability.

## Keep an eye out for ‘gotchas’

A variety of phenomena can distort shut-in transients. For example:

1. If the WHP reaches zero after shut-in, then the wellbore storage coefficient will abruptly increase by roughly two orders of magnitude, because of the effect of ‘falling liquid level’. If this occurs early in the shut-in (such as in high-permeability, subhydrostatic formations), this will cause a sudden flattening of the rate of pressure falloff, followed by a resumption of the downward curve. This may superficially look like the ‘compliance’ closure response – but it is not closure! Expect this signal if you reach WHP of zero early in a shut-in. If it occurs late in the transient (such as in low-permeability, subhydrostatic formations), then pressure will flatten until the end of the test, and the subsequent data is uninterpretable. Hegeman et al. (1993) provide a helpful discussion of ‘changing wellbore storage’ during conventional falloff tests.
2. In low permeability formations, late in the transient, you may see the rate of pressure falloff reach zero, and pressure may even increase slightly. Various processes could hypothetically cause this phenomenon. Overall, you should neglect data after the point where the log-log derivative falls off much steeper than -1.
3. In low permeability formations, late in the transient, the rate of pressure change is very slow, and the system is sensitive to perturbations. DFITs or fracture stimulation treatments performed in nearby wells can induce poroelastic stress response, or even direct fluid communication. If the responses are small, they can be ignored. If large, then the subsequent data cannot be interpreted.
4. In real data, we’ll sometimes see unexplained, unusual shapes in the pressure derivative plots. It is tempting try to interpret these wiggles and attempt to draw additional character from the interpretation. In cases with a clear rationale and explanation for what is happening, this may be acceptable. But generally, we caution against overinterpreting nonidealities in data, and if in doubt, conclude that you cannot confidently interpret the test. If you do want to test a hypothesis for what might have caused a particular observation, we’d recommend simulating the hypothesized explanation with a full-physics simulator, such as ResFrac, and comparing the simulated transient with the actual observations.
5. Please feel free to reach out to us at ResFrac if you ever have any questions.

## Acknowledgments

The recommendations in this paper are based on the interpretation procedure developed by the 2018 DFIT Industry Study, as outlined in URTeC-2019-123. We gratefully acknowledge the companies that sponsored this study – Apache, ConocoPhillips, Equinor, Hess, Keane, Range Resources, and Shell. This paper also derives from the results specified in SPE-205297. This paper was supported by a variety of operators who provided permission to provide their DFITs in the anonymized study, as listed in that paper’s acknowledgments.

## References

Bröker, Kai, and Xiaodong Ma. 2022. Estimating the least principal stress in a granitic rock mass: Systematic mini‑frac tests and elaborated pressure transient analysis. Rock Mechanics and Rock Engineering 391.

Dutler, Nathan, Benoit Valley, Valentin Gischig, Mohammadreza Jalali, Bernard Brixel, Hannes Krietsch, Clement Roques, and Florian Amann. 2020. Hydromechanical insight of fracture opening and closure during in-situ hydraulic fracturing in crystalline rock. International Journal of Rock Mechanics and Mining Sciences 135.

Guglielmi, Yves, Mark McClure, Jeffrey Burghardt, Joseph P. Morris, Thomas Doe, Pengcheng Fu, Hunter Knox, Vince Vermeul, Tim Kneafsey, and The EGS Collab Team. 2023. Using in-situ strain measurements to evaluate the accuracy of stress estimation procedures from fracture injection/shut-in tests. International Journal of Rock Mechanics and Mining Sciences 170.

Hegeman, Peter S., Debora L. Haliford, and Jeffrey A. Joseph. 1993. Well-test analysis with changing wellbore storage. SPE 21829. SPE Formation Evaluation.

Malik, Mayank, Ken Schwartz, Ken Moelhoff, and Vinay K. Mishra. 2014. Microfracturing in tight rocks: a Delaware Basin case study. SPE 169009. Paper presented at the SPE Unconventional Resources Conference, The Woodlands, TX.

McClure, Mark W., Hojung Jung, Dave D. Cramer, and Mukul M. Sharma. 2016. The fracture compliance method for picking closure pressure from diagnostic fracture injection tests. SPE Journal 21(4): 1321-1339.

McClure, Mark. 2017. The spurious deflection on log-log superposition-time derivative plots of diagnostic fracture-injection tests. SPE Reservoir Engineering and Evaluation 20(4): 1045-1055.

McClure, Mark, Vidya Bammidi, Craig Cipolla, Dave Cramer, Lucas Martin, Alexei A Savitski, Dave Sobernheim, and Kate Voller. 2019. URTeC-2019-123. A collaborative study on DFIT interpretation: Integrating modeling, field data, and analytical techniques. Paper presented at the Unconventional Resources Technology Conference, Denver, Colorado.

McClure, Mark, Garrett Fowler, and Matteo Picone. 2022. Best practices in DFIT interpretation: Comparative analysis of 62 DFITs from nine different shale plays. SPE 205297. Paper presented at the International Hydraulic Fracturing Technology Conference and Exhibition, Muscat, Oman.

Ye, Zhi, and Ahmad Ghassemi. 2023. Reexamining in-situ stress interpretation using laboratory hydraulic fracturing experiments. Paper presented at the 48<sup>th</sup> Workshop on Geothermal Reservoir Engineering, Stanford University.
